"""AD-722: Agent-observable avatar telemetry — read-side channel.

This module is the **single source of truth** for the backend signal-derivation
rule table consumed by ``observe_self_avatar()`` (CognitiveAgent) and the
``GET /api/agent/{id}/avatar-telemetry`` endpoint.

Read-only contract (non-negotiable in v1):
    Zero state mutations, zero LLM calls, zero writes, zero RecordsStore
    interaction. Every failure path tier-2 degrades — the snapshot is
    always returned (never raises) with affected fields set to None and a
    structured ``degraded_reasons`` tuple populated.

Signal derivation rules (mirrored from
``ui/src/components/profile/avatarSignals.ts`` ``deriveAgentSignals``):

  - ``trust_delta``  = ``runtime.trust_network.get_history(agent_id, limit=2)``
                       ``hist[-1] - hist[-2]`` when ``len(hist) >= 2``,
                       else ``0.0`` + ``"insufficient_trust_history"``.
                       Method existence is guarded via ``hasattr`` — mirrors
                       the call-site at ``routers/agents.py:91``.
  - ``working_state`` = ``"blocked"`` when ``agent.state == AgentState.DEGRADED``,
                       ``"responding"`` when ``load > 0``, else ``"idle"``.
  - ``load``         = v1 approximation: ``1.0 if mouth_active else 0.0``
                       (no canonical per-agent backend source at HEAD;
                       AD-722b's WebSocket channel makes this authoritative).
  - ``tier3_alert``  = ``any(a.severity == AlertSeverity.ALERT and
                       a.related_agent_id == agent_id
                       for a in runtime.bridge_alerts.get_recent_alerts(10))``;
                       when ``runtime.bridge_alerts is None`` → ``False`` +
                       ``"bridge_alerts_unavailable"``.

Modulation rule table (mirrors ``ui/src/audio/voiceModulation.ts`` constants
verbatim — byte-parity is enforced by ``test_modulation_byte_parity_with_ts``).
AD-722-1 is the consolidation forward marker (extract to YAML manifest).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from probos.avatars.dsl import AvatarDSL
from probos.bridge_alerts import AlertSeverity
from probos.types import AgentState

logger = logging.getLogger(__name__)


# ── Modulation rule table (TS↔Python byte-parity, enforced by test) ─────

MODULATION_DIVERGENCE_THRESHOLD: float = 0.05
PITCH_BOUNDS: tuple[float, float] = (0.0, 2.0)
RATE_BOUNDS: tuple[float, float] = (0.1, 10.0)
VOLUME_BOUNDS: tuple[float, float] = (0.0, 1.0)

TRUST_DELTA_HIGH: float = 0.2
TRUST_DELTA_LOW: float = -0.2

RESPONDING_RATE_FACTOR: float = 1.05
BLOCKED_RATE_FACTOR: float = 0.92
BLOCKED_PITCH_FACTOR: float = 0.95
HIGH_TRUST_PITCH_FACTOR: float = 1.03
LOW_TRUST_PITCH_FACTOR: float = 0.97
TIER3_RATE_FACTOR: float = 1.15
TIER3_VOLUME_FACTOR: float = 1.05

DEFAULT_PITCH: float = 0.9
DEFAULT_RATE: float = 0.95
DEFAULT_VOLUME: float = 0.8


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    lo, hi = bounds
    return max(lo, min(hi, value))


# ── Frozen dataclasses ──────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentSignalsSnapshot:
    """Read-only snapshot of the four AgentSignals fields.

    Mirrors ``ui/src/components/profile/avatarSignals.ts`` AgentSignals.
    """

    trust_delta: float
    load: float
    working_state: str  # 'idle' | 'responding' | 'blocked'
    tier3_alert: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "trust_delta": self.trust_delta,
            "load": self.load,
            "working_state": self.working_state,
            "tier3_alert": self.tier3_alert,
        }


@dataclass(frozen=True)
class ModulationSnapshot:
    """Post-clamp voice-modulation factors + fired-rule names.

    Multiplicative composition matches ``applyEmotionalModulation`` in TS.
    """

    pitch_factor: float
    rate_factor: float
    volume_factor: float
    fired_rules: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pitch_factor": self.pitch_factor,
            "rate_factor": self.rate_factor,
            "volume_factor": self.volume_factor,
            "fired_rules": list(self.fired_rules),
        }


@dataclass(frozen=True)
class DslSummarySnapshot:
    """Stable summary projection of an agent's persisted ``AvatarDSL``."""

    body_type: str
    hair_style: str
    primary_color: str
    outfit_style: str
    color_palette_hint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "body_type": self.body_type,
            "hair_style": self.hair_style,
            "primary_color": self.primary_color,
            "outfit_style": self.outfit_style,
            "color_palette_hint": self.color_palette_hint,
        }


@dataclass(frozen=True)
class AvatarTelemetrySnapshot:
    """Read-only snapshot of an agent's avatar state.

    Note on ``mouth_active``: speech happens browser-side via the Web Speech
    API; the backend has no authoritative "currently speaking" signal. v1
    derives ``mouth_active`` from ``(now - agent.last_reply_emitted_at) <
    cfg.avatar_telemetry.mouth_active_window_seconds`` (default 3.0s). This
    is a known approximation. AD-722b's WebSocket channel makes it
    authoritative.

    Note on ``load``: v1 approximates ``load = 1.0 if mouth_active else 0.0``
    (no canonical per-agent backend source at HEAD).

    Note on ``trust_delta``: v1 reads ``runtime.trust_network.get_history(
    agent_id, limit=2)`` behind a ``hasattr`` guard mirroring
    ``routers/agents.py:91``. When the method is absent OR history < 2
    entries → ``trust_delta=0.0`` + degraded reason
    ``"insufficient_trust_history"``. No magnitude smoothing, no decay.
    """

    agent_id: str
    expression_resting: str | None
    current_signals: AgentSignalsSnapshot
    mouth_active: bool
    applied_modulation: ModulationSnapshot | None
    dsl_summary: DslSummarySnapshot | None
    last_observed_at: float
    degraded_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "expression_resting": self.expression_resting,
            "current_signals": self.current_signals.to_dict(),
            "mouth_active": self.mouth_active,
            "applied_modulation": (
                self.applied_modulation.to_dict()
                if self.applied_modulation is not None else None
            ),
            "dsl_summary": (
                self.dsl_summary.to_dict() if self.dsl_summary is not None else None
            ),
            "last_observed_at": self.last_observed_at,
            "degraded_reasons": list(self.degraded_reasons),
        }


# ── Pure modulation function (mirrors applyEmotionalModulation in TS) ───


def apply_voice_modulation(
    profile: Any,
    signals: AgentSignalsSnapshot,
) -> ModulationSnapshot:
    """Pure function. Multiplicative composition matches voiceModulation.ts.

    ``profile`` is duck-typed to ``VoiceProfile`` (reads ``pitch`` / ``rate`` /
    ``volume`` attributes; falls back to module defaults when absent).

    Fired-rule names: ``'responding_rate'``, ``'blocked_rate_pitch'``,
    ``'high_trust_pitch'``, ``'low_trust_pitch'``, ``'tier3_rate_volume'``.
    """
    base_pitch = float(getattr(profile, "pitch", DEFAULT_PITCH))
    base_rate = float(getattr(profile, "rate", DEFAULT_RATE))
    base_volume = float(getattr(profile, "volume", DEFAULT_VOLUME))

    pitch = base_pitch
    rate = base_rate
    volume = base_volume
    fired: list[str] = []

    if signals.working_state == "responding":
        rate *= RESPONDING_RATE_FACTOR
        fired.append("responding_rate")
    elif signals.working_state == "blocked":
        rate *= BLOCKED_RATE_FACTOR
        pitch *= BLOCKED_PITCH_FACTOR
        fired.append("blocked_rate_pitch")

    if signals.trust_delta > TRUST_DELTA_HIGH:
        pitch *= HIGH_TRUST_PITCH_FACTOR
        fired.append("high_trust_pitch")
    elif signals.trust_delta < TRUST_DELTA_LOW:
        pitch *= LOW_TRUST_PITCH_FACTOR
        fired.append("low_trust_pitch")

    if signals.tier3_alert:
        rate *= TIER3_RATE_FACTOR
        volume *= TIER3_VOLUME_FACTOR
        fired.append("tier3_rate_volume")

    return ModulationSnapshot(
        pitch_factor=_clamp(pitch, PITCH_BOUNDS),
        rate_factor=_clamp(rate, RATE_BOUNDS),
        volume_factor=_clamp(volume, VOLUME_BOUNDS),
        fired_rules=tuple(fired),
    )


# ── Snapshot builder ────────────────────────────────────────────────────


def _empty_signals() -> AgentSignalsSnapshot:
    return AgentSignalsSnapshot(
        trust_delta=0.0, load=0.0, working_state="idle", tier3_alert=False,
    )


def _warn(reason: str, agent_id: str, field: str) -> None:
    logger.warning(
        "AD-722 telemetry: %s for agent=%s; field=%s set to None/default",
        reason, agent_id, field,
    )


async def build_telemetry_snapshot(
    agent_id: str,
    runtime: Any,
) -> AvatarTelemetrySnapshot:
    """Build a read-only avatar telemetry snapshot.

    Tier-2 log-and-degrade on every failure path. NEVER raises on missing
    data — degraded fields populate ``degraded_reasons`` instead.
    """
    reasons: list[str] = []
    now = time.time()

    # 1. Resolve agent.
    registry = getattr(runtime, "registry", None)
    agent = registry.get(agent_id) if registry is not None else None
    if agent is None:
        _warn("agent_not_found", agent_id, "all")
        return AvatarTelemetrySnapshot(
            agent_id=agent_id,
            expression_resting=None,
            current_signals=_empty_signals(),
            mouth_active=False,
            applied_modulation=None,
            dsl_summary=None,
            last_observed_at=now,
            degraded_reasons=("agent_not_found",),
        )

    # 2. Crew profile (mirrors routers/agents.py:124 pattern).
    crew = None
    profile_store = getattr(runtime, "profile_store", None)
    if profile_store is not None:
        try:
            crew = profile_store.get(agent_id)
        except Exception:
            crew = None
    appearance = getattr(crew, "appearance", None) if crew is not None else None
    if crew is None:
        reasons.append("crew_profile_missing")
        _warn("crew_profile_missing", agent_id, "dsl_summary+modulation")
    elif appearance is None:
        reasons.append("appearance_profile_missing")
        _warn("appearance_profile_missing", agent_id, "dsl_summary")

    # 3. Validate persisted DSL → DslSummarySnapshot.
    dsl_summary: DslSummarySnapshot | None = None
    expression_resting: str | None = None
    color_palette_hint = ""
    persisted_dsl = getattr(appearance, "dsl", None) if appearance is not None else None
    if appearance is not None:
        color_palette_hint = getattr(appearance, "color_palette_hint", "") or ""
    if persisted_dsl is None:
        if appearance is not None:
            reasons.append("dsl_not_persisted")
            _warn("dsl_not_persisted", agent_id, "dsl_summary")
    else:
        try:
            dsl = AvatarDSL.model_validate(persisted_dsl)
            expression_resting = str(dsl.expression_resting)
            dsl_summary = DslSummarySnapshot(
                body_type=str(dsl.body.type),
                hair_style=str(dsl.hair.style),
                primary_color=str(dsl.outfit.primary_color),
                outfit_style=str(dsl.outfit.style),
                color_palette_hint=color_palette_hint,
            )
        except ValidationError:
            reasons.append("dsl_invalid")
            _warn("dsl_invalid", agent_id, "dsl_summary")

    # 4. Trust delta — guarded mirror of routers/agents.py:91.
    trust_delta = 0.0
    trust_network = getattr(runtime, "trust_network", None)
    history: list[float] = []
    if trust_network is not None and hasattr(trust_network, "get_history"):
        try:
            raw = trust_network.get_history(agent_id, limit=2)
            history = list(raw) if raw is not None else []
        except Exception:
            history = []
    if len(history) < 2:
        reasons.append("insufficient_trust_history")
        _warn("insufficient_trust_history", agent_id, "trust_delta")
    else:
        try:
            trust_delta = float(history[-1]) - float(history[-2])
        except (TypeError, ValueError):
            trust_delta = 0.0
            reasons.append("trust_history_malformed")
            _warn("trust_history_malformed", agent_id, "trust_delta")

    # 5. Tier-3 alert — runtime.bridge_alerts.get_recent_alerts(10).
    bridge_alerts = getattr(runtime, "bridge_alerts", None)
    tier3_alert = False
    if bridge_alerts is None:
        reasons.append("bridge_alerts_unavailable")
        _warn("bridge_alerts_unavailable", agent_id, "tier3_alert")
    else:
        try:
            recent = bridge_alerts.get_recent_alerts(10)
        except Exception:
            recent = []
        for alert in recent or []:
            sev = getattr(alert, "severity", None)
            related = getattr(alert, "related_agent_id", None)
            if sev == AlertSeverity.ALERT and related == agent_id:
                tier3_alert = True
                break

    # 6. mouth_active — public property on CognitiveAgent.
    cfg = getattr(runtime, "config", None)
    telemetry_cfg = getattr(cfg, "avatar_telemetry", None)
    window = float(getattr(telemetry_cfg, "mouth_active_window_seconds", 3.0))
    last_emit = float(getattr(agent, "last_reply_emitted_at", 0.0) or 0.0)
    mouth_active = (last_emit > 0.0) and ((now - last_emit) < window)

    # 7. load — v1 approximation.
    load = 1.0 if mouth_active else 0.0

    # 8. working_state.
    state = getattr(agent, "state", None)
    if state == AgentState.DEGRADED:
        working_state = "blocked"
    elif load > 0.0:
        working_state = "responding"
    else:
        working_state = "idle"

    signals = AgentSignalsSnapshot(
        trust_delta=trust_delta,
        load=load,
        working_state=working_state,
        tier3_alert=tier3_alert,
    )

    # 9. applied_modulation — needs voice profile.
    applied_modulation: ModulationSnapshot | None = None
    voice_profile = getattr(crew, "voice", None) if crew is not None else None
    if voice_profile is None:
        reasons.append("voice_profile_missing")
        _warn("voice_profile_missing", agent_id, "applied_modulation")
    else:
        try:
            applied_modulation = apply_voice_modulation(voice_profile, signals)
        except Exception:
            reasons.append("voice_modulation_failed")
            _warn("voice_modulation_failed", agent_id, "applied_modulation")

    return AvatarTelemetrySnapshot(
        agent_id=agent_id,
        expression_resting=expression_resting,
        current_signals=signals,
        mouth_active=mouth_active,
        applied_modulation=applied_modulation,
        dsl_summary=dsl_summary,
        last_observed_at=now,
        degraded_reasons=tuple(reasons),
    )
