"""AD-491: Infodynamic telemetry endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.routers.deps import get_runtime

router = APIRouter(prefix="/api/infodynamic", tags=["analytics"])


@router.get("")
async def get_infodynamic(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Return the latest infodynamic entropy snapshot."""
    probe = getattr(runtime, "infodynamic_probe", None)
    if probe is None:
        raise HTTPException(404, "Infodynamic probe disabled")
    report = await probe.analyze()
    return {
        "generated_at": report.generated_at,
        "total_entropy_bits": report.total_entropy_bits,
        "signals": [
            {
                "name": s.name,
                "entropy": s.entropy,
                "sample_size": s.sample_size,
                "bucket_count": s.bucket_count,
            }
            for s in report.signals
        ],
    }
