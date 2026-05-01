"""AD-439: Emergent leadership analytics endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.routers.deps import get_runtime

router = APIRouter(prefix="/api/emergent-leadership", tags=["analytics"])


@router.get("")
async def get_emergent_leadership(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Return the latest emergent-leadership divergence report."""
    detector = getattr(runtime, "emergent_leadership_detector", None)
    if detector is None:
        raise HTTPException(404, "Emergent leadership detection disabled")
    report = detector.analyze()
    return {
        "generated_at": report.generated_at,
        "sample_size": report.sample_size,
        "skipped": report.skipped,
        "divergences": [
            {
                "agent_id": d.agent_id,
                "agent_type": d.agent_type,
                "designed_superior_post": d.designed_superior_post,
                "emergent_target_id": d.emergent_target_id,
                "emergent_weight": d.emergent_weight,
                "designed_weight": d.designed_weight,
                "detected_at": d.detected_at,
            }
            for d in report.divergences
        ],
    }
