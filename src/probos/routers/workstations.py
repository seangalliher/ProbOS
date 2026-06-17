"""AD-1022: read-only workstation-type catalog API.

Prefix ``/api/workstations``. Gated on ``config.workstations.enabled`` (default
OFF): ``GET /types`` returns an empty list when the feature is disabled, so the
router can be included unconditionally (matching api.py's flat include loop)
without changing any existing path or behavior — byte-identical when off.

Availability is computed from ``runtime.commercial_overlay_loaded`` (AD-697's
``is_commercial_loaded()``). **Security (DD-4):** the per-type render *target*
(``component_key``/``resource_uri``/``url``) is NEVER serialized — only the
``render_kind`` summary — and unavailable types are filtered out entirely before
serialization, so a commercial ``url`` can never leak to an OSS-mode client.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workstations", tags=["workstations"])


class WorkstationTypeView(BaseModel):
    """Public, render-target-free view of a workstation type (DD-4).

    Carries only the availability catalog summary — never the render target — so
    the model itself is the security guard against leaking a commercial ``url``.
    """

    id: str
    label: str
    tier: str
    available: bool
    render_kind: str


class WorkstationTypesResponse(BaseModel):
    """Response envelope for ``GET /api/workstations/types``."""

    types: list[WorkstationTypeView] = Field(default_factory=list)


@router.get("/types", response_model=WorkstationTypesResponse)
async def list_workstation_types(
    runtime: Any = Depends(get_runtime),
) -> WorkstationTypesResponse:
    """List available workstation types (render-target-free catalog).

    Dormant (empty list) unless ``config.workstations.enabled``. Availability is
    gated on the commercial-overlay flag; only available types are returned and
    the render target is never emitted (DD-4 security).
    """
    cfg = getattr(getattr(runtime, "config", None), "workstations", None)
    if cfg is None or not getattr(cfg, "enabled", False):
        return WorkstationTypesResponse(types=[])

    registry = getattr(runtime, "workstation_type_registry", None)
    if registry is None:
        logger.warning(
            "AD-1022: workstations enabled but registry unavailable; returning empty"
        )
        return WorkstationTypesResponse(types=[])

    commercial_loaded = bool(getattr(runtime, "commercial_overlay_loaded", False))
    views: list[WorkstationTypeView] = []
    for wtype in registry.list_available(commercial_loaded=commercial_loaded):
        views.append(
            WorkstationTypeView(
                id=wtype.id,
                label=wtype.label,
                tier=wtype.tier,
                available=True,
                render_kind=wtype.render.kind,
            )
        )
    return WorkstationTypesResponse(types=views)
