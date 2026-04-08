"""ProbOS API — System routes (AD-436, AD-471, AD-485, AD-488)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from probos.api_models import ShutdownRequest
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
    runtime: Any = Depends(get_runtime),
    track_task: Callable = Depends(get_task_tracker),
) -> dict[str, Any]:
    """AD-436: Initiate system shutdown from HXI Bridge."""
    async def _do_shutdown():
        await asyncio.sleep(1)
        await runtime.stop(reason=req.reason)
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
    engine = getattr(runtime, "_emergence_metrics_engine", None)
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
    engine = getattr(runtime, "_emergence_metrics_engine", None)
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
