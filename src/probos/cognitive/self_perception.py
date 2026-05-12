"""AD-722e (Wave 154): deterministic structured self-perception.

Reads the same source-of-truth that drives the avatar renderer
(``AppearanceProfile.dsl`` + ``AvatarTelemetrySnapshot``) and emits a
structured :class:`SelfPerceptionProjection` for use in INTEROCEPTION
sensorium blocks and (via AD-722a-1 future work) divergence detection.

v1 invariants (enforced by ``tests/test_ad727_safety_constraints.py``):

- **No vision-LLM calls.** The projector is a pure function over
  in-process state. AD-727 hard rule #4.
- **No browser-side screen capture.** No HTTP endpoint reads the
  canvas; no client-side capture library is imported. AD-727 hard
  rule #5.
- **Single agent parameter.** The function takes ``self_id`` only —
  comparative perception is a separate AD. AD-727 hard rule #7.
- **READ-ONLY w.r.t. trust/Hebbian.** Perception cannot mutate
  governance state. AD-727 hard rule #1.
- **Pipeline-version visibility.** The projection carries
  :data:`PIPELINE_VERSION` so renderer changes surface to the agent as
  observations, not silent self-mutations. AD-727 hard rule #2.

See :doc:`../../docs/architecture/self-perception-framing` for the
public-framing paragraph.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from probos.avatars.telemetry import build_telemetry_snapshot

logger = logging.getLogger(__name__)


# AD-727 rule #2: renderer-pipeline version. Bump any time the renderer's
# input contract changes so the agent sees the change as an observation
# rather than silent identity mutation.
PIPELINE_VERSION: str = "1.0.0"


@dataclass(frozen=True)
class SelfPerceptionProjection:
    """Structured projection of an agent's avatar state.

    Read-only by construction. Built from
    :class:`probos.avatars.telemetry.AvatarTelemetrySnapshot` — the same
    snapshot that drives the renderer — so projection and renderer cannot
    drift apart at the digital layer (AD-728 covers digital-vs-analog
    drift via a separate, gated vision-LLM call).
    """

    agent_id: str
    timestamp: float
    pipeline_version: str

    # DSL summary (renderer's structural input).
    dsl_body_type: str
    dsl_hair_style: str
    dsl_outfit_style: str
    dsl_primary_color: str

    # Live signals (renderer's dynamic input).
    working_state: str
    expression_resting: str | None
    mouth_active: bool
    modulation_rate_factor: float | None
    modulation_pitch_factor: float | None


async def project_self_perception(
    self_id: str,
    runtime: Any,
) -> SelfPerceptionProjection | None:
    """Project an agent's avatar state as a structured English description.

    Returns ``None`` when telemetry is disabled or no snapshot is available
    (tier-2 log-and-degrade — never raises).

    AD-727 rule #7: ``self_id`` is the only agent parameter. There is no
    peer / other-agent input. Cross-crew visual perception belongs to a
    separate AD.
    """
    cfg = getattr(runtime, "config", None)
    tcfg = getattr(cfg, "avatar_telemetry", None) if cfg is not None else None
    if tcfg is None or not getattr(tcfg, "enabled", False):
        return None

    try:
        snap = await build_telemetry_snapshot(self_id, runtime)
    except Exception:
        logger.debug(
            "AD-722e: telemetry snapshot build failed for %s; "
            "returning None projection",
            self_id,
            exc_info=True,
        )
        return None

    if snap is None:
        return None

    dsl = getattr(snap, "dsl_summary", None)
    signals = getattr(snap, "current_signals", None)
    modulation = getattr(snap, "applied_modulation", None)

    return SelfPerceptionProjection(
        agent_id=self_id,
        timestamp=time.time(),
        pipeline_version=PIPELINE_VERSION,
        dsl_body_type=getattr(dsl, "body_type", "") if dsl is not None else "",
        dsl_hair_style=getattr(dsl, "hair_style", "") if dsl is not None else "",
        dsl_outfit_style=getattr(dsl, "outfit_style", "") if dsl is not None else "",
        dsl_primary_color=getattr(dsl, "primary_color", "") if dsl is not None else "",
        working_state=getattr(signals, "working_state", "") if signals is not None else "",
        expression_resting=getattr(snap, "expression_resting", None),
        mouth_active=bool(getattr(snap, "mouth_active", False)),
        modulation_rate_factor=(
            getattr(modulation, "rate_factor", None)
            if modulation is not None else None
        ),
        modulation_pitch_factor=(
            getattr(modulation, "pitch_factor", None)
            if modulation is not None else None
        ),
    )
