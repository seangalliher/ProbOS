"""AD-722d: auto-write significant avatar telemetry events to Ship's Records.

Hooks the WS publish loop. Tier-2 — never raises out of public methods.
Throttle window is per-agent (default 1 hr); enforced via an in-memory
dict of last-write timestamps. Restart resets — intentional, see AD doc.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.avatars.telemetry import AvatarTelemetrySnapshot
    from probos.knowledge.records_store import RecordsStore

logger = logging.getLogger(__name__)

# v1 vocabulary; classify() returns a subset of these. Unknown names in
# config.records_significant_events are silently dropped at classify-time.
EVENT_EMOTION_DIVERGENCE_HIGH = "emotion_divergence_high"
EVENT_WORKING_STATE_TO_BLOCKED = "working_state_transition_to_blocked"
EVENT_SUSTAINED_SILENCE = "sustained_silence"

KNOWN_EVENTS: frozenset[str] = frozenset({
    EVENT_EMOTION_DIVERGENCE_HIGH,
    EVENT_WORKING_STATE_TO_BLOCKED,
    EVENT_SUSTAINED_SILENCE,
})


class TelemetryRecordsWriter:
    def __init__(
        self,
        *,
        records_store: "RecordsStore",
        runtime: Any,
        throttle_seconds: int,
        significant_events: list[str],
        sustained_silence_seconds: int,
        divergence_threshold: float,
    ) -> None:
        self._records = records_store
        self._runtime = runtime
        self._throttle_s = max(1, int(throttle_seconds))
        self._silence_s = max(60, int(sustained_silence_seconds))
        self._div_threshold = float(divergence_threshold)
        # Subset of v1 vocabulary the operator opted into. Unknown names dropped.
        self._enabled_events: frozenset[str] = frozenset(
            e for e in significant_events if e in KNOWN_EVENTS
        )
        self._prior: dict[str, "AvatarTelemetrySnapshot"] = {}
        # Parallel per-agent prior divergence magnitude. Required because
        # AvatarTelemetrySnapshot is a frozen dataclass and cannot carry
        # writer-side state. Used by _classify to detect FRESH divergence.
        self._prior_div_mag: dict[str, float] = {}
        self._last_write: dict[str, float] = {}

    async def observe(self, snap: "AvatarTelemetrySnapshot") -> None:
        """Classify + maybe write. Tier-2 — never raises."""
        try:
            events = self._classify(snap)
            # ALWAYS update prior, even if no events fire — needed for
            # accurate next-frame transition detection.
            self._prior[snap.agent_id] = snap
            if not events:
                return
            now = time.time()
            last = self._last_write.get(snap.agent_id, 0.0)
            if (now - last) < self._throttle_s:
                logger.debug(
                    "AD-722d: throttled for agent=%s (events=%s)",
                    snap.agent_id, sorted(events),
                )
                return
            # Pick highest-signal event (emotion_divergence > blocked > silence).
            event = self._pick_priority(events)
            await self._write(snap, event)
            self._last_write[snap.agent_id] = now
        except Exception:
            logger.warning(
                "AD-722d: observe failed for agent=%s",
                getattr(snap, "agent_id", "?"), exc_info=True,
            )

    def _classify(self, snap: "AvatarTelemetrySnapshot") -> set[str]:
        out: set[str] = set()
        prior = self._prior.get(snap.agent_id)

        # 1. emotion_divergence_high — read divergence_results latest entry.
        if EVENT_EMOTION_DIVERGENCE_HIGH in self._enabled_events:
            dr = getattr(self._runtime, "divergence_results", None)
            if dr is not None:
                latest = dr.get(snap.agent_id)
                if latest is not None and getattr(latest, "magnitude", 0.0) > self._div_threshold:
                    prior_mag = self._prior_div_mag.get(snap.agent_id, 0.0)
                    if latest.magnitude > prior_mag + 0.01:  # epsilon — only fresh rises
                        out.add(EVENT_EMOTION_DIVERGENCE_HIGH)
                    # ALWAYS update prior_div_mag so next frame compares against
                    # the latest observed magnitude (not a stale baseline).
                    self._prior_div_mag[snap.agent_id] = float(latest.magnitude)

        # 2. working_state transition to blocked.
        if EVENT_WORKING_STATE_TO_BLOCKED in self._enabled_events and prior is not None:
            prior_ws = getattr(prior.current_signals, "working_state", None)
            now_ws = getattr(snap.current_signals, "working_state", None)
            if now_ws == "blocked" and prior_ws != "blocked":
                out.add(EVENT_WORKING_STATE_TO_BLOCKED)

        # 3. sustained_silence — mouth_active False AND a real prior reply existed.
        if EVENT_SUSTAINED_SILENCE in self._enabled_events:
            registry = getattr(self._runtime, "registry", None)
            agent = registry.get(snap.agent_id) if registry is not None else None
            last_reply = getattr(agent, "last_reply_emitted_at", 0.0) or 0.0
            if last_reply > 0 and not snap.mouth_active:
                gap = time.time() - last_reply
                # Upper bound 4h: prevents stale-silence re-firing days later
                # after a restart; throttle handles re-fire within the window.
                if self._silence_s <= gap <= 4 * 3600:
                    out.add(EVENT_SUSTAINED_SILENCE)
        return out

    @staticmethod
    def _pick_priority(events: set[str]) -> str:
        # Stable priority — divergence beats blocked beats silence.
        for candidate in (
            EVENT_EMOTION_DIVERGENCE_HIGH,
            EVENT_WORKING_STATE_TO_BLOCKED,
            EVENT_SUSTAINED_SILENCE,
        ):
            if candidate in events:
                return candidate
        # Defensive: ordered set guarantees at least one element.
        return next(iter(events))

    async def _write(
        self,
        snap: "AvatarTelemetrySnapshot",
        event: str,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        clock = now_iso.split("T", 1)[-1][:5]  # "HH:MM"
        if event == EVENT_EMOTION_DIVERGENCE_HIGH:
            dr = getattr(self._runtime, "divergence_results", None)
            latest = dr.get(snap.agent_id) if dr is not None else None
            mag = getattr(latest, "magnitude", 0.0) if latest is not None else 0.0
            emotion = getattr(latest, "intent_emotion", "?") if latest is not None else "?"
            narrative = (
                f"At {clock}, voice modulation diverged from declared "
                f"emotion '{emotion}' (magnitude {mag:.2f})."
            )
        elif event == EVENT_WORKING_STATE_TO_BLOCKED:
            narrative = (
                f"At {clock}, working state transitioned to 'blocked'."
            )
        else:  # sustained_silence
            narrative = (
                f"At {clock}, sustained silence observed "
                f"(no reply emitted in > {self._silence_s // 60} minutes)."
            )
        path = (
            f"notebooks/{snap.agent_id}/telemetry-events-"
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"
        )
        content = f"- [{now_iso}] [{event}] {narrative}\n"
        try:
            await self._records.write_entry(
                author=snap.agent_id,
                path=path,
                content=content,
                message=f"telemetry: {event}",
                classification="ship",
                topic="avatar-telemetry",
                tags=["telemetry", event],
            )
        except Exception:
            logger.warning(
                "AD-722d: RecordsStore write failed for agent=%s event=%s",
                snap.agent_id, event, exc_info=True,
            )
