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

AD-722b: WS push channel consumes this snapshot via to_dict() — do NOT
add fields without updating the AD-722b WS frame contract test.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from probos.avatars.dsl import AvatarDSL
from probos.bridge_alerts import AlertSeverity
from probos.types import AgentState

logger = logging.getLogger(__name__)


# ── Modulation rule table (loaded from JSON manifest — AD-722-1) ────────
#
# Single source of truth: ``ui/src/audio/modulation_manifest.json``. Both
# this module and ``ui/src/audio/voiceModulation.ts`` read from that file.
# AD-722-1 retired the regex-based byte-parity test; drift is now structurally
# impossible (one file, two readers). Schema is enforced by
# ``_load_modulation_manifest()`` — every key listed below MUST be present.

import json as _json
from pathlib import Path as _Path


_MANIFEST_PATH: _Path = (
    _Path(__file__).resolve().parents[3]
    / "ui" / "src" / "audio" / "modulation_manifest.json"
)

_REQUIRED_SCALAR_KEYS: tuple[str, ...] = (
    "modulation_divergence_threshold",
    "trust_delta_high",
    "trust_delta_low",
    "responding_rate_factor",
    "blocked_rate_factor",
    "blocked_pitch_factor",
    "high_trust_pitch_factor",
    "low_trust_pitch_factor",
    "tier3_rate_factor",
    "tier3_volume_factor",
    "default_pitch",
    "default_rate",
    "default_volume",
)
_REQUIRED_BOUNDS_KEYS: tuple[str, ...] = (
    "pitch_bounds", "rate_bounds", "volume_bounds",
)
# AD-722a-7: nested-object keys (validated with their own field schemas).
_REQUIRED_OBJECT_KEYS: tuple[str, ...] = (
    "intent_rules",
)
_REQUIRED_INTENT_FIELDS: tuple[str, ...] = ("pitch", "rate", "volume", "rule_name")
_REQUIRED_INTENT_EMOTIONS: tuple[str, ...] = (
    "warm", "concerned", "excited", "apologetic",
    "formal", "playful", "reassuring", "neutral",
)
_INTENT_RULE_NAME_RE: re.Pattern[str] = re.compile(r"^intent_[a-z_]+$")


def _load_modulation_manifest() -> dict[str, Any]:
    """Load and validate the modulation manifest. Raises on any defect.

    Hard requirement at import — if the manifest is missing, malformed,
    or schema-incomplete, the module fails to import. This is by design:
    the rule table is non-optional; degraded fallback would silently
    re-introduce the duplication AD-722-1 exists to eliminate.
    """
    if not _MANIFEST_PATH.is_file():
        raise RuntimeError(
            f"AD-722-1: modulation manifest not found at {_MANIFEST_PATH}. "
            "ProbOS expects to run from the repo source tree; if you are "
            "running from a non-source layout, file a packaging AD."
        )
    try:
        data = _json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except _json.JSONDecodeError as exc:
        raise RuntimeError(
            f"AD-722-1: modulation manifest at {_MANIFEST_PATH} is malformed "
            f"JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError(
            f"AD-722-1: modulation manifest at {_MANIFEST_PATH} must be a "
            f"JSON object; got {type(data).__name__}"
        )
    missing = [k for k in _REQUIRED_SCALAR_KEYS + _REQUIRED_BOUNDS_KEYS
               if k not in data]
    if missing:
        raise RuntimeError(
            f"AD-722-1: modulation manifest missing required keys: {missing}"
        )
    # AD-722a-7: required nested-object keys are validated separately below.
    missing_objects = [k for k in _REQUIRED_OBJECT_KEYS if k not in data]
    if missing_objects:
        raise RuntimeError(
            f"AD-722a-7: modulation manifest missing required object keys: "
            f"{missing_objects}"
        )
    extra = [k for k in data
             if k not in (
                 _REQUIRED_SCALAR_KEYS
                 + _REQUIRED_BOUNDS_KEYS
                 + _REQUIRED_OBJECT_KEYS
             )]
    if extra:
        raise RuntimeError(
            f"AD-722-1: modulation manifest has unknown keys: {extra}. "
            "Schema additions require an architecture-decision review."
        )
    for k in _REQUIRED_SCALAR_KEYS:
        if not isinstance(data[k], (int, float)) or isinstance(data[k], bool):
            raise RuntimeError(
                f"AD-722-1: manifest key {k!r} must be a number; "
                f"got {type(data[k]).__name__}"
            )
    for k in _REQUIRED_BOUNDS_KEYS:
        b = data[k]
        if not (isinstance(b, list) and len(b) == 2
                and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                        for x in b)):
            raise RuntimeError(
                f"AD-722-1: manifest key {k!r} must be a 2-number list; "
                f"got {b!r}"
            )
    # AD-722a-7: validate intent_rules nested object.
    intent_rules = data["intent_rules"]
    if not isinstance(intent_rules, dict):
        raise RuntimeError(
            f"AD-722a-7: manifest key 'intent_rules' must be an object; "
            f"got {type(intent_rules).__name__}"
        )
    missing_emotions = [
        e for e in _REQUIRED_INTENT_EMOTIONS if e not in intent_rules
    ]
    if missing_emotions:
        raise RuntimeError(
            f"AD-722a-7: manifest 'intent_rules' missing required emotions: "
            f"{missing_emotions}"
        )
    extra_emotions = [
        e for e in intent_rules if e not in _REQUIRED_INTENT_EMOTIONS
    ]
    if extra_emotions:
        raise RuntimeError(
            f"AD-722a-7: manifest 'intent_rules' has unknown emotion keys: "
            f"{extra_emotions}. The v1 taxonomy is fixed; per-agent palettes "
            "are forward marker AD-722a-3."
        )
    for emotion, entry in intent_rules.items():
        if not isinstance(entry, dict):
            raise RuntimeError(
                f"AD-722a-7: manifest 'intent_rules[{emotion!r}]' must be an "
                f"object; got {type(entry).__name__}"
            )
        missing_fields = [
            f for f in _REQUIRED_INTENT_FIELDS if f not in entry
        ]
        if missing_fields:
            raise RuntimeError(
                f"AD-722a-7: manifest 'intent_rules[{emotion!r}]' missing "
                f"required fields: {missing_fields}"
            )
        for field in ("pitch", "rate", "volume"):
            val = entry[field]
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise RuntimeError(
                    f"AD-722a-7: manifest 'intent_rules[{emotion!r}].{field}' "
                    f"must be a number; got {type(val).__name__}"
                )
        rule_name = entry["rule_name"]
        if not isinstance(rule_name, str) or not _INTENT_RULE_NAME_RE.match(
            rule_name
        ):
            raise RuntimeError(
                f"AD-722a-7: manifest 'intent_rules[{emotion!r}].rule_name' "
                f"must match pattern {_INTENT_RULE_NAME_RE.pattern!r}; "
                f"got {rule_name!r}"
            )
    return data


_MANIFEST: dict[str, Any] = _load_modulation_manifest()

MODULATION_DIVERGENCE_THRESHOLD: float = float(_MANIFEST["modulation_divergence_threshold"])
PITCH_BOUNDS: tuple[float, float] = (
    float(_MANIFEST["pitch_bounds"][0]), float(_MANIFEST["pitch_bounds"][1]),
)
RATE_BOUNDS: tuple[float, float] = (
    float(_MANIFEST["rate_bounds"][0]), float(_MANIFEST["rate_bounds"][1]),
)
VOLUME_BOUNDS: tuple[float, float] = (
    float(_MANIFEST["volume_bounds"][0]), float(_MANIFEST["volume_bounds"][1]),
)

TRUST_DELTA_HIGH: float = float(_MANIFEST["trust_delta_high"])
TRUST_DELTA_LOW: float = float(_MANIFEST["trust_delta_low"])

RESPONDING_RATE_FACTOR: float = float(_MANIFEST["responding_rate_factor"])
BLOCKED_RATE_FACTOR: float = float(_MANIFEST["blocked_rate_factor"])
BLOCKED_PITCH_FACTOR: float = float(_MANIFEST["blocked_pitch_factor"])
HIGH_TRUST_PITCH_FACTOR: float = float(_MANIFEST["high_trust_pitch_factor"])
LOW_TRUST_PITCH_FACTOR: float = float(_MANIFEST["low_trust_pitch_factor"])
TIER3_RATE_FACTOR: float = float(_MANIFEST["tier3_rate_factor"])
TIER3_VOLUME_FACTOR: float = float(_MANIFEST["tier3_volume_factor"])

DEFAULT_PITCH: float = float(_MANIFEST["default_pitch"])
DEFAULT_RATE: float = float(_MANIFEST["default_rate"])
DEFAULT_VOLUME: float = float(_MANIFEST["default_volume"])

# AD-722a-7: intent rule table -- {emotion: {pitch, rate, volume, rule_name}}.
# Single source of truth: ui/src/audio/modulation_manifest.json (intent_rules
# section). The TS reader (voiceModulation.ts) consumes the same fields.
# rule_name is appended to ModulationSnapshot.fired_rules when the intent
# matches -- even when factors are all 1.0 (intent_neutral), preserving the
# "intent declared and parsed" signal for the divergence detector.
INTENT_RULES: dict[str, dict[str, Any]] = {
    name: {
        "pitch": float(entry["pitch"]),
        "rate": float(entry["rate"]),
        "volume": float(entry["volume"]),
        "rule_name": str(entry["rule_name"]),
    }
    for name, entry in _MANIFEST["intent_rules"].items()
}


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
    sampling_rate_ms: int                # AD-722f — agent's current adaptive sampling rate
    sampling_tier: str                   # AD-722f — 'high' | 'normal' | 'low'

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
            "sampling_rate_ms": self.sampling_rate_ms,
            "sampling_tier": self.sampling_tier,
        }


# ── Pure modulation function (mirrors applyEmotionalModulation in TS) ───


def apply_voice_modulation(
    profile: Any,
    signals: AgentSignalsSnapshot,
    intent: str | None = None,
) -> ModulationSnapshot:
    """Pure function. Multiplicative composition matches voiceModulation.ts.

    ``profile`` is duck-typed to ``VoiceProfile`` (reads ``pitch`` / ``rate`` /
    ``volume`` attributes; falls back to module defaults when absent).

    Fired-rule names: ``'responding_rate'``, ``'blocked_rate_pitch'``,
    ``'high_trust_pitch'``, ``'low_trust_pitch'``, ``'tier3_rate_volume'``.

    AD-722a-7: when ``intent`` is set to a known emotion name (one of
    ``INTENT_RULES.keys()``), the corresponding ``intent_X`` rule fires
    AFTER operational rules and multiplies onto the post-operational
    factors. ``intent_neutral`` is recorded as a no-op (rule_name is
    appended to fired_rules even though all factors are 1.0). Unknown
    intent names are silently dropped -- ``parse_intent_self_tag`` already
    filters at the boundary.
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

    # AD-722a-7: intent layering. Intent rule applies AFTER operational
    # rules, multiplies onto current factors, then the final clamp covers
    # both stages. ``intent_neutral`` (and any rule with all-1.0 factors)
    # is recorded in fired_rules even though factors don't change --
    # preserves the "intent declared and parsed" signal for divergence
    # detection.
    if intent is not None:
        rule = INTENT_RULES.get(intent)
        if rule is not None:
            pitch *= rule["pitch"]
            rate *= rule["rate"]
            volume *= rule["volume"]
            fired.append(rule["rule_name"])

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


def _resolve_sampling(
    runtime: Any, agent_id: str, reasons: list[str],
) -> tuple[int, str]:
    """AD-722f: resolve current adaptive sampling rate + tier for an agent.

    Tier-2 log-and-degrade: when the state machine is missing (test
    runtimes with stripped MagicMocks), fall back to LOW using the
    config's default rate; append a degraded reason. NEVER raises.
    """
    state = getattr(runtime, "avatar_sampling_state", None)
    cfg = getattr(runtime, "config", None)
    tcfg = getattr(cfg, "avatar_telemetry", None)
    rates = getattr(tcfg, "sampling_rates", None)
    if state is None:
        reasons.append("avatar_sampling_state_unavailable")
        low_ms = getattr(rates, "low_ms", 10000)
        return int(low_ms), "low"
    try:
        tier = state.current_tier(agent_id)
        rate = state.current_rate_ms(agent_id)
        return int(rate), str(tier)
    except Exception:
        logger.warning(
            "AD-722f: sampling-state lookup failed for agent=%s; "
            "falling back to LOW",
            agent_id, exc_info=True,
        )
        reasons.append("avatar_sampling_state_unavailable")
        low_ms = getattr(rates, "low_ms", 10000)
        return int(low_ms), "low"


def _warn(reason: str, agent_id: str, field: str) -> None:
    logger.warning(
        "AD-722 telemetry: %s for agent=%s; field=%s set to None/default",
        reason, agent_id, field,
    )


async def build_telemetry_snapshot(
    agent_id: str,
    runtime: Any,
    intent_emotion: str | None = None,
) -> AvatarTelemetrySnapshot:
    """Build a read-only avatar telemetry snapshot.

    Tier-2 log-and-degrade on every failure path. NEVER raises on missing
    data -- degraded fields populate ``degraded_reasons`` instead.

    AD-722a-7: ``intent_emotion`` is threaded through to
    ``apply_voice_modulation`` so the ``applied_modulation.fired_rules``
    carries the corresponding ``intent_X`` rule. The divergence path in
    ``apply_divergence_check`` uses this to compute match scores against
    the intent_* namespace.
    """
    reasons: list[str] = []
    now = time.time()

    # 1. Resolve agent.
    registry = getattr(runtime, "registry", None)
    agent = registry.get(agent_id) if registry is not None else None
    if agent is None:
        _warn("agent_not_found", agent_id, "all")
        # AD-722f: agent_not_found path — emit LOW tier with config defaults.
        _early_reasons: list[str] = ["agent_not_found"]
        _early_rate_ms, _early_tier = _resolve_sampling(
            runtime, agent_id, _early_reasons,
        )
        return AvatarTelemetrySnapshot(
            agent_id=agent_id,
            expression_resting=None,
            current_signals=_empty_signals(),
            mouth_active=False,
            applied_modulation=None,
            dsl_summary=None,
            last_observed_at=now,
            degraded_reasons=tuple(_early_reasons),
            sampling_rate_ms=_early_rate_ms,
            sampling_tier=_early_tier,
        )

    # 2. Crew profile (mirrors routers/agents.py 3-tier fallback: live ProfileStore →
    #    seed YAML → typed defaults). Crew profiles are created lazily — most agents
    #    won't have a persisted profile until the Captain modifies their voice or
    #    appearance, so falling all the way to defaults is the common case, not an
    #    error.
    from probos.crew_profile import (
        AppearanceProfile,
        CrewProfile,
        VoiceProfile,
        load_seed_profile_async,
    )
    from probos.voice_profile_defaults import default_voice_for

    crew: CrewProfile | None = None
    profile_store = getattr(runtime, "profile_store", None)
    if profile_store is not None:
        try:
            crew = profile_store.get(agent_id)
        except Exception:
            crew = None

    seed: dict[str, Any] = {}
    if crew is None:
        agent_type = getattr(agent, "agent_type", "")
        try:
            seed = await load_seed_profile_async(agent_type) or {}
        except Exception:
            seed = {}
        # Build a synthetic in-memory CrewProfile from seed + defaults so the
        # rest of the assembly path uses one consistent shape. Not persisted.
        seed_voice = seed.get("voice") if isinstance(seed.get("voice"), dict) else None
        voice = (
            VoiceProfile.from_dict(seed_voice)
            if seed_voice
            else default_voice_for(agent_type)
        )
        seed_appearance = (
            seed.get("appearance") if isinstance(seed.get("appearance"), dict) else None
        )
        appearance = (
            AppearanceProfile.from_dict(seed_appearance)
            if seed_appearance
            else AppearanceProfile()
        )
        crew = CrewProfile(
            agent_id=agent_id,
            agent_type=agent_type,
            voice=voice,
            appearance=appearance,
        )
        # Distinguish "fell back to defaults" from "no data at all" — the former
        # is normal for unmodified crew; the latter is the original signal we
        # surfaced before this fix. Keep the reason but make it accurate.
        if seed_voice or seed_appearance:
            reasons.append("crew_profile_seeded")
        else:
            reasons.append("crew_profile_default")

    appearance = crew.appearance
    if appearance is None:
        # Crew exists but has no appearance profile — data inconsistency
        # (default factory should always populate it). Surface it.
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

    # 9. applied_modulation — voice profile is normally always populated
    #    (live or defaulted from seed/typed defaults in step 2). The only
    #    way it's None here is data corruption on a live crew profile
    #    (default factory should always populate it). Surface that case.
    applied_modulation: ModulationSnapshot | None = None
    voice_profile = crew.voice
    if voice_profile is None:
        reasons.append("voice_profile_missing")
        _warn("voice_profile_missing", agent_id, "applied_modulation")
    else:
        try:
            applied_modulation = apply_voice_modulation(
                voice_profile, signals, intent=intent_emotion,
            )
        except Exception:
            reasons.append("voice_modulation_failed")
            _warn("voice_modulation_failed", agent_id, "applied_modulation")

    # AD-722f: resolve adaptive sampling rate/tier for the success path.
    sampling_rate_ms, sampling_tier = _resolve_sampling(
        runtime, agent_id, reasons,
    )

    return AvatarTelemetrySnapshot(
        agent_id=agent_id,
        expression_resting=expression_resting,
        current_signals=signals,
        mouth_active=mouth_active,
        applied_modulation=applied_modulation,
        dsl_summary=dsl_summary,
        last_observed_at=now,
        degraded_reasons=tuple(reasons),
        sampling_rate_ms=sampling_rate_ms,
        sampling_tier=sampling_tier,
    )
