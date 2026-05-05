"""ProbOS API — Clinical Telemetry routes (AD-635d).

Thin REST pass-through over ``ClinicalTelemetryService`` (AD-635 v1, AD-635b,
AD-635c). Four GET endpoints:

  * ``GET /api/clinical/dreams``
  * ``GET /api/clinical/chain-traces/{agent_id}``
  * ``GET /api/clinical/circuit-breakers/{agent_id}``
  * ``GET /api/clinical/audit``

The clearance gate lives inside the service (``_authorize_clinical_query``);
the REST layer is shape-conversion only. Every successful call is recorded
on the in-memory audit ring by the service itself, so the REST layer adds
no separate audit hook.

Service-unavailable (``runtime.clinical_telemetry`` is None or missing,
which is the default when ``ClinicalTelemetryConfig.enabled=False``)
returns HTTP 503. Clearance-denied calls return HTTP 200 with an empty
list (mirrors the underlying service contract — denial is logged on the
audit ring, not surfaced to the caller).

REST authentication is deferred to AD-635d-1 (matches every other
unauthenticated router in the current codebase).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/clinical", tags=["clinical"])


def _service(runtime: Any) -> Any:
    """Return ``runtime.clinical_telemetry`` or None when unavailable."""
    return getattr(runtime, "clinical_telemetry", None)


def _service_unavailable() -> JSONResponse:
    """Construct a fresh 503 response per call (Response objects are not reused)."""
    return JSONResponse(
        {"error": "Clinical telemetry not available"},
        status_code=503,
    )


@router.get("/dreams")
async def get_dreams(
    requester_agent_id: str,
    limit: int = 20,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-635d: Recent dream-cycle reports, most recent first.

    Args:
        requester_agent_id: REQUIRED. Caller-asserted agent identity.
            The clearance gate inside ``query_dream_history`` validates it.
        limit: Max rows (default 20, hard-capped at 100).
    """
    service = _service(runtime)
    if service is None:
        return _service_unavailable()
    rows = await service.query_dream_history(
        requester_agent_id=requester_agent_id,
        limit=min(max(limit, 1), 100),
    )
    return {
        "requester_agent_id": requester_agent_id,
        "dreams": rows,
    }


@router.get("/chain-traces/{agent_id}")
async def get_chain_traces(
    agent_id: str,
    requester_agent_id: str,
    limit: int = 20,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-635d: Recent cognitive-chain traces for one agent, most recent first.

    Args:
        agent_id: Path param — the target agent whose traces are queried.
        requester_agent_id: REQUIRED query param. Clearance-gated by service.
        limit: Max rows (default 20, hard-capped at 500).
    """
    service = _service(runtime)
    if service is None:
        return _service_unavailable()
    rows = await service.query_agent_chain_traces(
        requester_agent_id=requester_agent_id,
        target_agent_id=agent_id,
        limit=min(max(limit, 1), 500),
    )
    return {
        "requester_agent_id": requester_agent_id,
        "target_agent_id": agent_id,
        "traces": rows,
    }


@router.get("/circuit-breakers/{agent_id}")
async def get_circuit_breaker_history(
    agent_id: str,
    requester_agent_id: str,
    limit: int = 50,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-635d: Recent circuit-breaker state + zone transitions for one agent.

    Args:
        agent_id: Path param — the target agent whose breaker history is queried.
        requester_agent_id: REQUIRED query param. Clearance-gated by service.
        limit: Max rows (default 50, hard-capped at 500).
    """
    service = _service(runtime)
    if service is None:
        return _service_unavailable()
    rows = await service.query_circuit_breaker_history(
        requester_agent_id=requester_agent_id,
        target_agent_id=agent_id,
        limit=min(max(limit, 1), 500),
    )
    return {
        "requester_agent_id": requester_agent_id,
        "target_agent_id": agent_id,
        "transitions": rows,
    }


@router.get("/audit")
async def get_audit(
    limit: int = 200,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-635d: Snapshot of the in-memory clinical audit ring.

    Returns the most-recent ``limit`` entries (the ring is append-most-
    recent-last, so the slice is ``[-limit:]``). Hard-capped at 1000
    (matches the default ring capacity).

    NOT clearance-gated at the REST layer — same contract as the
    in-process ``audit_log`` property. AD-635d-1 covers REST-layer auth.
    """
    service = _service(runtime)
    if service is None:
        return _service_unavailable()
    snapshot = service.audit_log
    capped = min(max(limit, 1), 1000)
    return {"audit": snapshot[-capped:]}
