"""AD-733a: VisionWorkingMemory — per-agent ring buffer of vision observations.

The hot buffer used for prompt-context injection. Capacity 8 by default;
configurable via PerceptionConfig.working_memory_capacity. In-RAM only —
AD-742f forward marker for persistence across restart. AD-541b-anchored
episodes ARE persisted (those are the canonical long-term memory); this
buffer is the working-set projection.

Confabulation guard (BF-294 lesson): callers MUST treat empty buffer as
"no current visual data" rather than silently omitting context. The
``render_for_prompt`` method returns the explicit empty-state string.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class VisionObservation:
    """One supervisor-flagged + LLM-described frame."""
    timestamp: float
    attachment_ref: str        # SHA-256 of frame bytes in AttachmentStore (AD-731)
    description: str           # vision LLM output, truncated to ~400 chars
    novelty_score: float       # 0.0–1.0 from supervisor
    subject_identity: str = "unknown"  # "captain" | "unknown" | "other" — AD-733b populates
    session_id: str = ""


class VisionWorkingMemory:
    """Thread-safe per-agent ring buffer. One instance per agent_id per runtime."""

    def __init__(self, *, capacity: int = 8) -> None:
        self._buf: deque[VisionObservation] = deque(maxlen=capacity)
        self._lock = Lock()

    def append(self, obs: VisionObservation) -> None:
        with self._lock:
            self._buf.append(obs)

    def entries(self) -> list[VisionObservation]:
        with self._lock:
            return list(self._buf)

    def latest(self) -> VisionObservation | None:
        with self._lock:
            return self._buf[-1] if self._buf else None

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    def render_for_prompt(self, *, now: float | None = None) -> str:
        """Render the buffer for LLM prompt injection.

        Confabulation guard: when empty, returns a non-empty string that
        explicitly says no visual data is available. The agent's prompt
        builder MUST receive a clear "no data" signal rather than an
        empty string the agent might fill in from imagination.
        """
        entries = self.entries()
        if not entries:
            return (
                "--- Current Visual Context ---\n"
                "Camera not active or no frames described yet. "
                "Do NOT describe what you cannot see.\n"
                "--- End Visual Context ---"
            )

        now_ts = time.time() if now is None else now
        latest = entries[-1]
        age_s = max(0.0, now_ts - latest.timestamp)
        age_str = _format_age(age_s)

        lines = [
            "--- Current Visual Context ---",
            (
                f"Most recent observation ({age_str} ago, "
                f"novelty={latest.novelty_score:.2f}, "
                f"subject={latest.subject_identity}):"
            ),
            f"  {latest.description}",
        ]
        if len(entries) > 1:
            lines.append(f"Prior {len(entries) - 1} observation(s) in working memory.")
        lines.append("--- End Visual Context ---")
        return "\n".join(lines)


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds // 3600)}h"


__all__ = ["VisionWorkingMemory", "VisionObservation"]
