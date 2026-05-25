"""ProbOS API — System routes (AD-436, AD-471, AD-485, AD-488)."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from probos.api_models import ShutdownRequest
from probos.proactive import build_proactive_status_snapshot
from probos.routers.deps import get_runtime, get_task_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    status = runtime.status()
    return {
        "status": "ok",
        "crew_agents": status.get("crew_agents", 0),
        "agents": status.get("total_agents", 0),
        "health": round(
            sum(
                a.confidence
                for a in runtime.registry.all()
            ) / max(1, runtime.registry.count),
            2,
        ),
    }


@router.get("/status")
async def status(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    return runtime.status()


@router.get("/proactive/status")
async def proactive_status(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-752: Captain-facing proactive automation status."""
    snapshot = build_proactive_status_snapshot(runtime)
    return {
        "next_inbox_scan": snapshot.next_inbox_scan,
        "next_calendar_scan": snapshot.next_calendar_scan,
        "work_hours_active": snapshot.work_hours_active,
        "quiet_hours_active": snapshot.quiet_hours_active,
        "last_scan_count": snapshot.last_scan_count,
    }


@router.get("/extensions")
async def extensions(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-697: read-only snapshot of overlay extensions registered with the runtime.

    HXI / external clients use this to gate UI affordances ("show
    upgrade prompt", "render Admin tab") without needing to import any
    commercial symbol.
    """
    from probos.extensions.overlay import registered_hook_names, registered_pre_intent_auth_hook_names
    return {
        "commercial_loaded": runtime.commercial_overlay_loaded,
        "providers": list(runtime.loaded_extension_providers),
        "hooks": list(registered_hook_names()),
        "pre_intent_auth_hooks": list(registered_pre_intent_auth_hook_names()),
    }


class SystemExtensionsResponse(BaseModel):
    """BF-321 (#790): response model for ``/api/system/extensions`` stub."""

    extensions: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/system/extensions", response_model=SystemExtensionsResponse)
async def list_system_extensions() -> SystemExtensionsResponse:
    """BF-321 (#790): stub for the UI's extensions poller.

    Empty list until extension infrastructure lands (see roadmap #788
    absorption + future mcp-dynamic-registration AD). Exists solely to
    silence the 30s-interval ``/api/system/extensions`` 404 spam from
    ``CommercialOverlayBadge``.
    """
    return SystemExtensionsResponse(extensions=[])


@router.get("/causal-templates")
async def causal_templates(
    runtime: Any = Depends(get_runtime),
    agent_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """AD-660b: read-only access to recent causal-reasoning templates.

    Returns templates most-recent-first. Optional ``agent_id`` filter
    scopes to a single agent; otherwise ship-wide. Returns empty list
    when the journal is unavailable or causal reasoning is disabled.
    """
    journal = getattr(runtime, "cognitive_journal", None)
    if journal is None:
        return {"templates": [], "count": 0}
    try:
        rows = await journal.get_recent_causal_templates(
            limit=max(1, min(int(limit), 200)),
            agent_id=agent_id,
        )
    except Exception:
        logger.warning("AD-660b: causal-templates query failed", exc_info=True)
        return {"templates": [], "count": 0}
    return {"templates": list(rows or []), "count": len(rows or [])}


# AD-473d: Web Push subscription registry (lazy module-level singleton)
_PUSH_REGISTRY: Any = None


def _get_push_registry() -> Any:
    global _PUSH_REGISTRY
    if _PUSH_REGISTRY is None:
        from probos.web_push import PushSubscriptionRegistry
        _PUSH_REGISTRY = PushSubscriptionRegistry()
    return _PUSH_REGISTRY


@router.post("/push/subscribe")
async def push_subscribe(payload: dict[str, Any]) -> dict[str, Any]:
    """AD-473d: register a Web Push subscription.

    Expects W3C-shaped body: ``{endpoint, keys: {p256dh, auth}, subscriber_id?}``.
    Returns the registered subscription as a structured echo.
    """
    endpoint = (payload or {}).get("endpoint", "")
    keys = (payload or {}).get("keys", {}) or {}
    subscriber_id = (payload or {}).get("subscriber_id", "") or ""
    if not endpoint:
        return JSONResponse({"error": "endpoint required"}, status_code=400)
    registry = _get_push_registry()
    try:
        sub = registry.register(endpoint=endpoint, keys=keys, subscriber_id=subscriber_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"endpoint": sub.endpoint, "subscriber_id": sub.subscriber_id, "created_at": sub.created_at}


@router.post("/push/unsubscribe")
async def push_unsubscribe(payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = (payload or {}).get("endpoint", "")
    if not endpoint:
        return JSONResponse({"error": "endpoint required"}, status_code=400)
    registry = _get_push_registry()
    removed = registry.unregister(endpoint)
    return {"removed": removed}


@router.get("/push/subscriptions")
async def push_list_subscriptions() -> dict[str, Any]:
    """AD-473d: count of active push subscriptions (no PII returned)."""
    registry = _get_push_registry()
    return {"count": registry.count()}


@router.get("/telemetry")
async def get_telemetry(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Return current telemetry report (AD-461)."""
    telemetry = getattr(runtime, "_telemetry_service", None)
    if not telemetry:
        return {"status": "disabled", "operations": {}}
    return telemetry.get_report()


@router.get("/disclosure-clearances")
async def get_disclosure_clearances(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Return disclosure clearance configuration (AD-679)."""
    disclosure_router = getattr(runtime, "_disclosure_router", None)
    if not disclosure_router:
        return {"status": "disabled"}
    return {
        "status": "active",
        "department_clearances": disclosure_router.get_clearance_map(),
    }


@router.get("/decision-queue")
async def get_decision_queue(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Return decision queue status (AD-445)."""
    queue = getattr(runtime, "_decision_queue", None)
    if not queue:
        return {"status": "disabled"}
    return {
        **queue.get_summary(),
        "decisions": [d.to_dict() for d in queue.get_all()],
    }


@router.post("/decision-queue/pause")
async def pause_decision_queue(
    body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Pause the decision queue (AD-445)."""
    queue = getattr(runtime, "_decision_queue", None)
    if not queue:
        return {"status": "disabled"}
    reason = body.get("reason", "")
    queue.pause(reason)
    return {"status": "paused", "reason": reason}


@router.post("/decision-queue/resume")
async def resume_decision_queue(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Resume the decision queue (AD-445)."""
    queue = getattr(runtime, "_decision_queue", None)
    if not queue:
        return {"status": "disabled"}
    queue.resume()
    return {"status": "resumed"}


@router.get("/task-router")
async def get_task_router(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Return task routing configuration (AD-438)."""
    task_router = getattr(runtime, "_task_router", None)
    if not task_router:
        return {"status": "disabled", "mappings": {}}
    return {
        "status": "active",
        "mappings": task_router.list_mappings(),
    }


@router.get("/intent-metrics")
async def get_intent_metrics(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Return IntentBus metrics (AD-470)."""
    intent_bus = getattr(runtime, "intent_bus", None)
    if not intent_bus:
        return {"status": "disabled"}
    return {
        "metrics": intent_bus.get_metrics(),
        "subscribers": intent_bus.get_subscriber_map(),
        "subscriber_count": intent_bus.subscriber_count,
    }


@router.get("/system/services")
async def system_services(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-436: Service status for Bridge System panel."""
    services = []
    checks = [
        ("Ward Room", runtime.ward_room),
        ("Episodic Memory", runtime.episodic_memory),
        ("Trust Network", runtime.trust_network),
        ("Knowledge Store", getattr(runtime, '_knowledge_store', None)),
        ("Cognitive Journal", getattr(runtime, 'cognitive_journal', None)),
        ("Codebase Index", getattr(runtime, 'codebase_index', None)),
        ("Skill Framework", getattr(runtime, 'skill_registry', None)),
        ("Skill Service", getattr(runtime, 'skill_service', None)),
        ("ACM", getattr(runtime, 'acm', None)),
        ("Hebbian Router", getattr(runtime, 'hebbian_router', None)),
        ("Intent Bus", getattr(runtime, 'intent_bus', None)),
    ]
    for name, svc in checks:
        if svc is None:
            svc_status = "offline"
        else:
            svc_status = "online"
        services.append({"name": name, "status": svc_status})

    # BF-069: LLM proxy health
    llm_client = getattr(runtime, 'llm_client', None)
    if llm_client and hasattr(llm_client, 'get_health_status'):
        health = llm_client.get_health_status()
        overall = health.get("overall", "unknown")
        if overall == "operational":
            llm_status = "online"
        elif overall == "degraded":
            llm_status = "degraded"
        else:
            # BF-108: "mock" and "offline" both map to offline
            llm_status = "offline"
        services.append({"name": "LLM Proxy", "status": llm_status})
    else:
        services.append({"name": "LLM Proxy", "status": "offline"})

    return {"services": services}


@router.get("/system/llm-health")
async def llm_health(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """BF-069: Detailed LLM proxy health status per tier."""
    llm_client = getattr(runtime, 'llm_client', None)
    if llm_client and hasattr(llm_client, 'get_health_status'):
        return llm_client.get_health_status()
    return {"tiers": {}, "overall": "unknown"}


@router.get("/system/circuit-breakers")
async def system_circuit_breakers(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-488: Circuit breaker status for all tracked agents."""
    if not hasattr(runtime, 'proactive_loop') or not runtime.proactive_loop:
        return {"breakers": []}
    cb = runtime.proactive_loop.circuit_breaker
    statuses = cb.get_all_statuses()
    for s in statuses:
        agent = runtime.registry.get(s["agent_id"])
        if agent:
            s["callsign"] = getattr(agent, 'callsign', agent.agent_type)
    return {"breakers": statuses}


@router.post("/system/shutdown")
async def system_shutdown(
    req: ShutdownRequest,
    request: Request,
    runtime: Any = Depends(get_runtime),
    track_task: Callable = Depends(get_task_tracker),
) -> dict[str, Any]:
    """AD-436: Initiate system shutdown from HXI Bridge.

    BF (2026-05-12): Log loudly on both entry and just before os._exit so silent
    shutdowns no longer leave the operator guessing whether a kill came from
    inside (this endpoint) or outside (Stop-Process / taskkill).
    """
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    reason = req.reason or "(no reason)"
    logger.warning(
        "/api/system/shutdown invoked: client=%s reason=%r user_agent=%r pid=%d",
        client_host, reason, user_agent, os.getpid(),
    )

    async def _do_shutdown():
        await asyncio.sleep(1)
        try:
            await runtime.stop(reason=req.reason)
        except Exception:
            logger.exception("runtime.stop() raised during /system/shutdown")
        logger.warning(
            "/api/system/shutdown calling os._exit(0): client=%s reason=%r pid=%d",
            client_host, reason, os.getpid(),
        )
        # Flush stdlib logging so the warning above isn't lost across os._exit.
        for h in logging.getLogger().handlers:
            try:
                h.flush()
            except Exception:
                pass
        os._exit(0)

    track_task(_do_shutdown(), name="system-shutdown")
    return {"status": "shutting_down", "reason": req.reason}


@router.get("/system/conn")
async def get_conn_status(runtime: Any = Depends(get_runtime)) -> Any:
    """Get current conn delegation status."""
    if not runtime.conn_manager:
        return JSONResponse({"active": False, "holder": None})
    return JSONResponse(runtime.conn_manager.get_status())


@router.get("/system/night-orders")
async def get_night_orders_status(runtime: Any = Depends(get_runtime)) -> Any:
    """Get current Night Orders status."""
    if not hasattr(runtime, '_night_orders_mgr') or not runtime._night_orders_mgr:
        return JSONResponse({"active": False})
    return JSONResponse(runtime._night_orders_mgr.get_status())


@router.get("/system/watch")
async def get_watch_status(runtime: Any = Depends(get_runtime)) -> Any:
    """Get watch bill status."""
    if not hasattr(runtime, 'watch_manager') or not runtime.watch_manager:
        return JSONResponse({"error": "Watch manager not initialized"}, status_code=404)
    return JSONResponse(runtime.watch_manager.get_watch_status())


@router.get("/system/communications/settings")
async def get_communications_settings(runtime: Any = Depends(get_runtime)):
    """Get current communications settings."""
    return {
        "dm_min_rank": runtime.config.communications.dm_min_rank,
        "recreation_min_rank": runtime.config.communications.recreation_min_rank,
    }


@router.patch("/system/communications/settings")
async def update_communications_settings(body: dict, runtime: Any = Depends(get_runtime)):
    """Update communications settings. Captain only."""
    valid_ranks = ["ensign", "lieutenant", "commander", "senior"]
    if "dm_min_rank" in body:
        rank_val = body["dm_min_rank"].lower()
        if rank_val not in valid_ranks:
            raise HTTPException(status_code=400, detail=f"Invalid rank. Must be one of: {valid_ranks}")
        runtime.config.communications.dm_min_rank = rank_val
    if "recreation_min_rank" in body:
        rank_val = body["recreation_min_rank"].lower()
        if rank_val not in valid_ranks:
            raise HTTPException(status_code=400, detail=f"Invalid rank. Must be one of: {valid_ranks}")
        runtime.config.communications.recreation_min_rank = rank_val
    return await get_communications_settings(runtime=runtime)


@router.post("/notifications/{notification_id}/ack")
async def ack_notification(notification_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Acknowledge a single notification (AD-323)."""
    ok = runtime.notification_queue.acknowledge(notification_id)
    return {"acknowledged": ok}


@router.post("/notifications/ack-all")
async def ack_all_notifications(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Acknowledge all unread notifications (AD-323)."""
    count = runtime.notification_queue.acknowledge_all()
    return {"acknowledged": count}


@router.get("/emergence")
async def get_emergence_metrics(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-557: Return cached emergence metrics from last dream cycle."""
    engine = getattr(runtime, "emergence_metrics_engine", None)
    if not engine:
        return {"status": "not_available", "message": "Emergence metrics engine not wired"}
    snapshot = engine.latest_snapshot
    if not snapshot:
        return {"status": "no_data", "message": "No emergence metrics computed yet"}
    return {"status": "ok", **snapshot.to_dict()}


@router.get("/emergence/history")
async def get_emergence_history(
    limit: int = 20,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-557: Return emergence metrics time series."""
    engine = getattr(runtime, "emergence_metrics_engine", None)
    if not engine:
        return {"status": "not_available", "snapshots": []}
    snapshots = engine.snapshots
    return {
        "status": "ok",
        "count": len(snapshots),
        "snapshots": [s.to_dict() for s in snapshots[-limit:]],
    }


@router.get("/behavioral-metrics")
async def get_behavioral_metrics(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-569: Return cached behavioral metrics from last dream cycle."""
    engine = getattr(runtime, "_behavioral_metrics_engine", None)
    if not engine:
        return {"status": "not_available", "message": "Behavioral metrics engine not wired"}
    snapshot = engine.latest_snapshot
    if not snapshot:
        return {"status": "no_data", "message": "No behavioral metrics computed yet"}
    return {"status": "ok", **snapshot.to_dict()}


@router.get("/behavioral-metrics/history")
async def get_behavioral_metrics_history(
    limit: int = 20,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-569: Return behavioral metrics time series."""
    engine = getattr(runtime, "_behavioral_metrics_engine", None)
    if not engine:
        return {"status": "not_available", "snapshots": []}
    snapshots = engine.snapshots
    return {
        "status": "ok",
        "count": len(snapshots),
        "snapshots": [s.to_dict() for s in snapshots[-limit:]],
    }


@router.get("/oracle")
async def oracle_query(
    q: str,
    agent_id: str = "",
    k: int = 3,
    tiers: str = "",
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-462e: Cross-tier unified memory query."""
    oracle = getattr(runtime, "_oracle_service", None)
    if not oracle:
        return {"status": "not_available", "message": "Oracle service not wired"}
    tier_list = [t.strip() for t in tiers.split(",") if t.strip()] or None
    results = await oracle.query(q, agent_id=agent_id, k_per_tier=k, tiers=tier_list)
    return {
        "status": "ok",
        "count": len(results),
        "results": [
            {"source_tier": r.source_tier, "content": r.content[:500], "score": r.score,
             "provenance": r.provenance, "metadata": r.metadata}
            for r in results
        ],
    }


@router.get("/notebook-quality")
async def get_notebook_quality(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-555: Return cached notebook quality metrics from last dream cycle."""
    engine = getattr(runtime, "_notebook_quality_engine", None)
    if not engine:
        return {"status": "not_available", "message": "Notebook quality engine not initialized"}
    snapshot = engine.latest_snapshot
    if not snapshot:
        return {"status": "no_data", "message": "No quality metrics computed yet — next dream cycle will generate"}
    return {"status": "ok", **snapshot.to_dict()}


@router.get("/notebook-quality/history")
async def get_notebook_quality_history(
    limit: int = 20,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-555: Return notebook quality time series."""
    engine = getattr(runtime, "_notebook_quality_engine", None)
    if not engine:
        return {"status": "not_available", "snapshots": []}
    snaps = engine.snapshots
    limited = snaps[-limit:] if len(snaps) > limit else snaps
    return {
        "status": "ok",
        "count": len(limited),
        "snapshots": [s.to_dict() for s in limited],
    }


@router.get("/notebook-quality/agent/{callsign}")
async def get_agent_notebook_quality(
    callsign: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-555: Per-agent notebook quality from latest snapshot."""
    engine = getattr(runtime, "_notebook_quality_engine", None)
    if not engine or not engine.latest_snapshot:
        return {"status": "no_data"}
    for aq in engine.latest_snapshot.per_agent:
        if aq.callsign.lower() == callsign.lower():
            return {"status": "ok", **aq.to_dict()}
    return {"status": "not_found", "message": f"No quality data for {callsign}"}


# --- AD-580: Alert resolution feedback ---


@router.post("/alerts/dismiss")
async def dismiss_alert(
    body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
) -> dict[str, str]:
    """AD-580: Dismiss an alert for a specified duration."""
    bas = getattr(runtime, "bridge_alerts", None)
    if not bas:
        raise HTTPException(404, "bridge_alerts not enabled")
    key = body.get("dedup_key", "")
    if not key:
        raise HTTPException(400, "dedup_key required")
    duration = body.get("duration_seconds")
    bas.dismiss_alert(key, duration)
    return {"status": "dismissed", "dedup_key": key}


@router.post("/alerts/resolve")
async def resolve_alert(
    body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
) -> dict[str, str]:
    """AD-580: Mark an alert as resolved."""
    bas = getattr(runtime, "bridge_alerts", None)
    if not bas:
        raise HTTPException(404, "bridge_alerts not enabled")
    key = body.get("dedup_key", "")
    if not key:
        raise HTTPException(400, "dedup_key required")
    bas.resolve_alert(key)
    return {"status": "resolved", "dedup_key": key}


@router.post("/alerts/mute")
async def mute_alert(
    body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
) -> dict[str, str]:
    """AD-580: Indefinitely mute an alert."""
    bas = getattr(runtime, "bridge_alerts", None)
    if not bas:
        raise HTTPException(404, "bridge_alerts not enabled")
    key = body.get("dedup_key", "")
    if not key:
        raise HTTPException(400, "dedup_key required")
    bas.mute_alert(key)
    return {"status": "muted", "dedup_key": key}


@router.post("/alerts/unmute")
async def unmute_alert(
    body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
) -> dict[str, str]:
    """AD-580: Remove indefinite suppression for an alert."""
    bas = getattr(runtime, "bridge_alerts", None)
    if not bas:
        raise HTTPException(404, "bridge_alerts not enabled")
    key = body.get("dedup_key", "")
    if not key:
        raise HTTPException(400, "dedup_key required")
    bas.unmute_alert(key)
    return {"status": "unmuted", "dedup_key": key}


@router.get("/alerts/suppressed")
async def alerts_suppressed(
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-580: List all currently suppressed alerts."""
    bas = getattr(runtime, "bridge_alerts", None)
    if not bas:
        return {"status": "no_data", "suppressed": []}
    return {"status": "ok", "suppressed": bas.list_suppressed()}

# --- AD-597: MCP App Host endpoints ---


@router.post("/mcp/jsonrpc")
async def mcp_jsonrpc(request: Request, runtime: Any = Depends(get_runtime)):
    """AD-597a: forward MCP JSON-RPC payload to FederationMCPServer."""
    if getattr(runtime, "federation_mcp_server", None) is None:
        raise HTTPException(status_code=503, detail="MCP server not running")
    payload = await request.json()
    session_id = request.headers.get("mcp-session-id", "")
    response = await runtime.federation_mcp_server.handle_jsonrpc(
        payload, session_id=session_id
    )
    headers: dict[str, str] = {}
    assigned = response.pop("_assigned_session", None) if isinstance(response, dict) else None
    if assigned:
        headers["Mcp-Session-Id"] = assigned
    return JSONResponse(response, headers=headers)


@router.get("/mcp/resource")
async def mcp_resource(uri: str, runtime: Any = Depends(get_runtime)):
    """AD-597a: serve ui:// resource as HTTP for iframe embedding."""
    registry = getattr(runtime, "mcp_app_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="MCP App registry not running")
    result = await registry.read_resource(uri)
    if result is None:
        raise HTTPException(status_code=404, detail=f"resource not found: {uri}")
    contents = result.get("contents", []) if isinstance(result, dict) else []
    if not contents:
        raise HTTPException(status_code=404, detail="empty resource")
    body = contents[0].get("text", "") or ""
    mime = registry.get_resource_mime(uri) or "text/html"
    csp = registry.get_resource_csp(uri)
    headers = {"Content-Security-Policy": csp} if csp else {}
    return Response(content=body, media_type=mime, headers=headers)


# ── AD-721: 3D crew avatars ─────────────────────────────────────


@router.get("/system/avatars/{filename}")
async def get_avatar(filename: str, runtime: Any = Depends(get_runtime)) -> Any:
    """AD-721 D6: Serve a .vrm model from data/avatars/.

    Path-traversal defense: resolve the requested file under the configured
    avatars dir and reject anything outside it. Reject files larger than
    `avatars.max_vrm_size_bytes` (default 25 MB).

    BF #539: ``avatars_dir`` is rooted under ``_platform_data_dir()`` (matches
    BF-265 split-brain prevention) when relative, instead of process cwd. Absolute
    paths pass through unchanged. The default ``"data/avatars"`` resolves to
    ``<platform_data_dir>/avatars`` (since ``_platform_data_dir()`` already ends
    in ``/data``).
    """
    cfg = getattr(runtime, "config", None)
    if cfg is None or not getattr(cfg, "avatars", None) or not cfg.avatars.enabled:
        raise HTTPException(status_code=404, detail="avatars disabled")
    avatars_dir = _resolve_avatars_dir(cfg.avatars.avatars_dir)
    target = (avatars_dir / filename).resolve()
    try:
        target.relative_to(avatars_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="avatar not found")
    if target.stat().st_size > cfg.avatars.max_vrm_size_bytes:
        raise HTTPException(status_code=413, detail="avatar exceeds size limit")
    return FileResponse(str(target), media_type="application/octet-stream")


def _resolve_avatars_dir(configured: str) -> Path:
    """BF #539: resolve avatars_dir consistently with the rest of ProbOS.

    Absolute path -> use as-is. Relative path -> root under the platform data
    dir (matching the BF-265 pattern other resources use). A leading ``data/``
    or ``data\\\\`` prefix in the configured value is stripped because
    ``_platform_data_dir()`` already terminates in ``/data``.
    """
    from probos.runtime import _platform_data_dir

    p = Path(configured)
    if p.is_absolute():
        return p.resolve()
    parts = p.parts
    if parts and parts[0].lower() == "data":
        # Strip the leading "data" segment to avoid <platform>/data/data/avatars
        parts = parts[1:]
    return (_platform_data_dir().joinpath(*parts) if parts else _platform_data_dir()).resolve()


@router.get("/config/avatars-enabled")
async def avatars_enabled(runtime: Any = Depends(get_runtime)) -> dict[str, bool]:
    """AD-721 D8: Surface the avatars feature-flag to the HXI."""
    cfg = getattr(runtime, "config", None)
    enabled = bool(cfg and getattr(cfg, "avatars", None) and cfg.avatars.enabled)
    return {"enabled": enabled}
