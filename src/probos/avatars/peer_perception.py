"""AD-729: peer avatar perception governance contract.

Wave 163 ships the contract — DSL, dataclass, four mechanical floors, capability
surface stub, RecordsStore artifact, federation gate. The Standing Orders
content (AD-729a) and the training/qualification flow (AD-729b) and the
Counselor pattern-monitoring (AD-729c) are separate ADs.

Hard mechanical constraints (code-enforced):
  1. Read-only on reputation + associative routing — peer observations
     never write trust scores or routing weights. Source-scan regression
     test enforces zero imports of those subsystems from this module.
  2. Privacy opt-out — observed agents whose ``CrewProfile.peer_perception
     .enabled`` is False are never recorded as observed_id.
  3. Backend render only — observers MUST source the analog signal from
     the backend render path. Browser captures are rejected.
  4. Cross-federation gate — when ``observed_id`` resolves outside the local
     registry, the call honest-degrades with ``federation_review_required``.

AD-727 inheritance: peer perception is governed by the same isolation rules
that govern AD-722e-2 and AD-722a-1; this module never wires into reputation
or routing.

AD-731 invariant: peer observations are textual. This module never carries
inline image bytes; no base64 inlining anywhere in the path.

Default OFF: ``cfg.avatars.peer_perception_enabled`` ships False. AD-729b
certification ALSO required (observer-side ``peer_perception.certified``
flag, default False at AgentDesigner spawn).
"""
from __future__ import annotations

import dataclasses
import enum
import logging
import secrets
import time
from collections import defaultdict
from threading import RLock
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ObservationRegister(str, enum.Enum):
    OPERATIONAL = "operational"
    PERSONAL = "personal"


@dataclasses.dataclass(frozen=True)
class PeerObservation:
    observer_id: str
    observed_id: str
    register: ObservationRegister
    content: str
    timestamp: float
    decay_after: float
    permission_grant_id: str | None


_PERMISSION_TTL_SECONDS = 5 * 60
_lock = RLock()
_grants: dict[str, dict[str, Any]] = {}
_pair_thread_usage: dict[tuple[str, str, str], int] = defaultdict(int)
_listeners: dict[str, Callable[[str, str], bool]] = {}
_observations: list[PeerObservation] = []


def reset_state() -> None:
    """Test helper: clear all in-module state."""
    with _lock:
        _grants.clear()
        _pair_thread_usage.clear()
        _listeners.clear()
        _observations.clear()


def register_permission_listener(
    observed_id: str,
    listener: Callable[[str, str], bool],
) -> None:
    with _lock:
        _listeners[observed_id] = listener


async def request_permission(
    *,
    runtime: Any,
    observer_id: str,
    observed_id: str,
) -> str | None:
    """AD-729 speak-freely protocol.

    Tier-2: never raises.
    """
    from probos.events import EventType

    await _emit(runtime, EventType.PEER_OBSERVATION_PERMISSION_REQUESTED, {
        "observer_id": observer_id,
        "observed_id": observed_id,
        "timestamp": time.time(),
    })

    with _lock:
        listener = _listeners.get(observed_id)

    granted = False
    if listener is not None:
        try:
            granted = bool(listener(observer_id, observed_id))
        except Exception:
            logger.warning(
                "AD-729: permission listener raised for observer=%s observed=%s; "
                "treating as deny",
                observer_id, observed_id, exc_info=True,
            )
            granted = False

    if not granted:
        await _emit(runtime, EventType.PEER_OBSERVATION_PERMISSION_DENIED, {
            "observer_id": observer_id,
            "observed_id": observed_id,
            "timestamp": time.time(),
        })
        return None

    grant_id = secrets.token_hex(16)
    with _lock:
        _grants[grant_id] = {
            "observer_id": observer_id,
            "observed_id": observed_id,
            "expires_at": time.time() + _PERMISSION_TTL_SECONDS,
            "consumed": False,
        }
        expires_at = _grants[grant_id]["expires_at"]
    await _emit(runtime, EventType.PEER_OBSERVATION_PERMISSION_GRANTED, {
        "observer_id": observer_id,
        "observed_id": observed_id,
        "grant_id": grant_id,
        "expires_at": expires_at,
    })
    return grant_id


def _consume_grant(grant_id: str, observer_id: str, observed_id: str) -> bool:
    now = time.time()
    with _lock:
        record = _grants.get(grant_id)
        if record is None:
            return False
        if record["consumed"]:
            return False
        if record["expires_at"] <= now:
            return False
        if record["observer_id"] != observer_id or record["observed_id"] != observed_id:
            return False
        record["consumed"] = True
    return True


async def observe_peer(
    *,
    runtime: Any,
    observer_id: str,
    observed_id: str,
    register: ObservationRegister,
    content: str,
    permission_grant_id: str | None = None,
    thread_id: str = "default",
    backend_render_available: bool = True,
) -> PeerObservation | None:
    """AD-729 governed peer-observation capability surface.

    Returns the recorded ``PeerObservation`` on the happy path; ``None`` on
    every honest-degrade. NEVER raises.
    """
    from probos.events import EventType

    async def _decline(reason: str) -> None:
        await _emit(runtime, EventType.PEER_OBSERVATION_DECLINED, {
            "observer_id": observer_id,
            "observed_id": observed_id,
            "register": register.value,
            "reason": reason,
            "timestamp": time.time(),
        })

    cfg = getattr(runtime, "config", None)
    avatars_cfg = getattr(cfg, "avatars", None) if cfg is not None else None
    if avatars_cfg is None or not getattr(avatars_cfg, "peer_perception_enabled", False):
        await _decline("capability_disabled")
        return None

    max_per_pair = int(getattr(avatars_cfg, "peer_observation_max_per_pair_per_thread", 0))
    if max_per_pair <= 0:
        await _decline("capability_disabled")
        return None

    registry = getattr(runtime, "registry", None)
    observer_profile = _peer_perception_profile_for(registry, observer_id)
    observed_profile = _peer_perception_profile_for(registry, observed_id)

    if observed_profile is None:
        await _decline("federation_review_required")
        return None
    if observer_profile is None:
        await _decline("observer_unknown")
        return None
    if not observer_profile.enabled:
        await _decline("observer_disabled")
        return None
    if not observer_profile.certified:
        await _decline("observer_uncertified")
        return None
    if not observed_profile.enabled:
        await _decline("observed_opted_out")
        return None

    if register == ObservationRegister.PERSONAL:
        if permission_grant_id is None:
            await _decline("permission_required")
            return None
        if not _consume_grant(permission_grant_id, observer_id, observed_id):
            await _decline("permission_invalid")
            return None

    if not backend_render_available:
        await _decline("backend_render_unavailable")
        return None

    pair_key = (observer_id, observed_id, thread_id)
    with _lock:
        if _pair_thread_usage[pair_key] >= max_per_pair:
            already_at_cap = True
        else:
            already_at_cap = False
            _pair_thread_usage[pair_key] += 1
    if already_at_cap:
        await _decline("pair_thread_rate_limited")
        return None

    now = time.time()
    decay_after = now + int(getattr(avatars_cfg, "peer_observation_decay_seconds", 86400 * 7))
    observation = PeerObservation(
        observer_id=observer_id,
        observed_id=observed_id,
        register=register,
        content=content[:500],
        timestamp=now,
        decay_after=decay_after,
        permission_grant_id=permission_grant_id,
    )
    with _lock:
        _observations.append(observation)

    await _persist_to_records(runtime, observation)
    await _emit(runtime, EventType.PEER_OBSERVATION_RECORDED, {
        "observer_id": observer_id,
        "observed_id": observed_id,
        "register": register.value,
        "content": observation.content,
        "timestamp": observation.timestamp,
        "decay_after": observation.decay_after,
    })
    return observation


def composite_impressions_for(
    *,
    runtime: Any,
    observed_id: str,
) -> str | None:
    """Return a single-paragraph string describing undecayed impressions of
    ``observed_id``. ``None`` when capability disabled, observed opted-out,
    or no undecayed observations.

    Section 6 v1: the actual integration into ``project_self_perception`` is
    deferred — see forward marker AD-729-impressions-hookup.
    """
    cfg = getattr(runtime, "config", None)
    avatars_cfg = getattr(cfg, "avatars", None) if cfg is not None else None
    if avatars_cfg is None or not getattr(avatars_cfg, "peer_perception_enabled", False):
        return None

    registry = getattr(runtime, "registry", None)
    observed_profile = _peer_perception_profile_for(registry, observed_id)
    if observed_profile is None or not observed_profile.enabled:
        return None

    now = time.time()
    with _lock:
        active = [
            o for o in _observations
            if o.observed_id == observed_id and o.decay_after > now
        ]
    if not active:
        return None

    parts = [
        f"{o.observer_id} ({o.register.value}): {o.content}"
        for o in active
    ]
    return "Crew impressions over the last window: " + " | ".join(parts)


def _peer_perception_profile_for(registry: Any, agent_id: str) -> Any:
    if registry is None:
        return None
    try:
        agent = registry.get(agent_id)
    except Exception:
        return None
    if agent is None:
        return None
    profile = getattr(agent, "profile", None) or getattr(agent, "crew_profile", None)
    if profile is None:
        return None
    return getattr(profile, "peer_perception", None)


async def _emit(runtime: Any, event_type: Any, payload: dict[str, Any]) -> None:
    emit = getattr(runtime, "emit_event", None)
    if emit is None:
        return
    try:
        result = emit(event_type, payload)
        if hasattr(result, "__await__"):
            await result
    except Exception:
        logger.warning(
            "AD-729: emit_event failed for %s; observation lost",
            event_type, exc_info=True,
        )


async def _persist_to_records(runtime: Any, observation: PeerObservation) -> None:
    store = getattr(runtime, "records_store", None)
    if store is None:
        return

    rel_path = (
        f"peer_observations/{observation.observer_id}_"
        f"{observation.observed_id}_{int(observation.timestamp * 1000)}.md"
    )
    content = (
        f"register: {observation.register.value}\n\n"
        f"{observation.content}\n"
    )

    try:
        result = store.write_entry(
            author=observation.observer_id,
            path=rel_path,
            content=content,
            message=(
                f"peer observation {observation.observer_id}->"
                f"{observation.observed_id}"
            ),
            classification="ship",
            status="recorded",
            department="counselor",
            topic="peer_observation",
            tags=["peer_observation", observation.register.value],
        )
        if hasattr(result, "__await__"):
            await result
    except Exception:
        logger.warning(
            "AD-729: records_store.write_entry failed for observer=%s observed=%s; degrading",
            observation.observer_id, observation.observed_id, exc_info=True,
        )


__all__ = [
    "ObservationRegister",
    "PeerObservation",
    "composite_impressions_for",
    "observe_peer",
    "observe_peer_divergence",
    "register_permission_listener",
    "request_permission",
    "reset_state",
]


# ---------------------------------------------------------------------------
# AD-722a-6 — Cross-agent intent-vs-presentation divergence observation.
# Consumer of AD-722a-1 divergence history + AD-729 governance contract.
# ---------------------------------------------------------------------------


def _format_divergence_summary(history_entries: list[Any]) -> str:
    """Render a stable, predictable OPERATIONAL-register summary of one
    agent's recent intent-vs-presentation divergences.

    Pure template — no LLM call, no embeddings. Phrasing is deliberately
    flat (no value-judgment vocabulary) so the AD-729 governance layer's
    expectations stay predictable.
    """
    if not history_entries:
        return "No recent intent-vs-presentation divergences observed."
    count = len(history_entries)
    magnitudes: list[float] = []
    emotion_counts: dict[str, int] = {}
    for entry in history_entries:
        result = getattr(entry, "result", None)
        if result is None:
            continue
        magnitudes.append(float(getattr(result, "magnitude", 0.0)))
        emo = str(getattr(result, "intent_emotion", "") or "unspecified")
        emotion_counts[emo] = emotion_counts.get(emo, 0) + 1
    mean_mag = sum(magnitudes) / len(magnitudes) if magnitudes else 0.0
    dominant_emotion = "unspecified"
    if emotion_counts:
        dominant_emotion = max(emotion_counts.items(), key=lambda kv: kv[1])[0]
    return (
        f"Observed {count} intent-vs-presentation divergences in the "
        f"recent window, dominant in the {dominant_emotion!r} category, "
        f"mean magnitude {mean_mag:.2f}."
    )


async def observe_peer_divergence(
    *,
    runtime: Any,
    observer_id: str,
    observed_id: str,
    register: ObservationRegister = ObservationRegister.OPERATIONAL,
    permission_grant_id: str | None = None,
    thread_id: str = "default",
    window_seconds: float = 86400.0,
) -> PeerObservation | None:
    """AD-722a-6 peer perception of intent-vs-presentation divergence.

    Reads AD-722a-1's per-agent divergence_history (lazily allocated on the
    runtime by ``divergence_detector``), summarises the recent entries with
    a flat OPERATIONAL-phrasing template, and routes the resulting
    observation through ``observe_peer()`` so AD-729's governance gates
    apply uniformly.

    Hard gates BEFORE delegating to ``observe_peer``:
      1. ``cfg.avatars.cross_agent_divergence_observation_enabled``
      2. AD-722a-1's ``vision_intent_divergence_enabled`` upstream gate
      3. observed has at least one divergence_history entry inside
         ``window_seconds``
    """
    from probos.events import EventType

    cfg = getattr(runtime, "config", None)
    avatars_cfg = getattr(cfg, "avatars", None) if cfg is not None else None
    if avatars_cfg is None or not getattr(
        avatars_cfg, "cross_agent_divergence_observation_enabled", False
    ):
        return None
    if not getattr(avatars_cfg, "vision_intent_divergence_enabled", False):
        return None

    history_map = getattr(runtime, "divergence_history", None)
    if history_map is None:
        return None
    bucket = history_map.get(observed_id)
    if bucket is None:
        return None

    now = time.time()
    recent = [
        entry for entry in bucket
        if (now - float(getattr(entry, "timestamp", 0.0))) <= window_seconds
    ]
    if not recent:
        return None

    summary = _format_divergence_summary(recent)

    observation = await observe_peer(
        runtime=runtime,
        observer_id=observer_id,
        observed_id=observed_id,
        register=register,
        content=summary,
        permission_grant_id=permission_grant_id,
        thread_id=thread_id,
        backend_render_available=True,
    )
    if observation is None:
        return None

    await _emit(runtime, EventType.CROSS_AGENT_DIVERGENCE_OBSERVED, {
        "observer_id": observer_id,
        "observed_id": observed_id,
        "register": observation.register.value,
        "summary": summary,
        "divergence_count": len(recent),
        "timestamp": observation.timestamp,
    })
    return observation
