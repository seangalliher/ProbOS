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

import re
import time
from collections import deque
from dataclasses import dataclass
from threading import Lock


# AD-1059: standing disposition for the visual feed. Prepended inside the
# rendered scene block (NOT the empty/stale sentinel, which keeps its own
# confabulation guard) so an agent treats the camera as BACKGROUND context and
# stops over-narrating an unchanged scene. Behavioral layer that complements the
# AD-1031 salience gate + AD-1060 frequency taper (engineering). Wording avoids
# capability-gap phrasing (no "can't"/"unable") so it never trips the gap regex.
_VISUAL_DISPOSITION: str = (
    "(This visual feed is BACKGROUND context. Do not narrate it by default. "
    "Mention what you see only when it is genuinely novel or unusual, when it is "
    "directly relevant to the task, or when the Captain asks — a brief, natural "
    "acknowledgement when a call first opens is welcome.)"
)


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
    """Thread-safe per-agent ring buffer. One instance per agent_id per runtime.

    AD-742f: when a ``store`` + ``agent_id`` are provided, the ring is
    auto-loaded from SQLite on construction and every ``append`` is
    mirrored to disk (best-effort, honest-degrade on failure).
    """

    def __init__(
        self,
        *,
        capacity: int = 8,
        store: object | None = None,
        agent_id: str = "",
    ) -> None:
        self._buf: deque[VisionObservation] = deque(maxlen=capacity)
        self._lock = Lock()
        self._store = store
        self._agent_id = str(agent_id)
        # AD-742f: hydrate ring from disk if a store is wired.
        if self._store is not None and self._agent_id:
            try:
                rows = self._store.load_for_agent(self._agent_id, capacity=capacity)
                for obs in rows:
                    self._buf.append(obs)
            except Exception:
                # Honest-degrade: store reported unavailable or row decode failed.
                # Tier-2 — never raise from __init__.
                pass

    def append(self, obs: VisionObservation) -> None:
        with self._lock:
            self._buf.append(obs)
        # AD-742f: best-effort persist. Outside the lock so a slow DB write
        # doesn't block in-memory reads.
        if self._store is not None and self._agent_id:
            try:
                self._store.append(self._agent_id, obs, capacity=self._buf.maxlen or 8)
            except Exception:
                pass

    def entries(self) -> list[VisionObservation]:
        with self._lock:
            return list(self._buf)

    def latest(self) -> VisionObservation | None:
        with self._lock:
            return self._buf[-1] if self._buf else None

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    def render_for_prompt(
        self, *, now: float | None = None, freshness_s: float | None = None,
    ) -> str:
        """Render the buffer for LLM prompt injection.

        Confabulation guard: when empty, returns a non-empty string that
        explicitly says no visual data is available. The agent's prompt
        builder MUST receive a clear "no data" signal rather than an
        empty string the agent might fill in from imagination.

        AD-1055: ``freshness_s`` — when set (> 0), a latest observation OLDER
        than this many seconds is treated as "no current visual data" (the
        same camera-off sentinel). The AD-742f ring is disk-persisted, so
        without this guard a frame from a PRIOR session survives a restart and
        the agent describes a scene it can no longer see (the BF-624 class:
        "a 22h-old black shirt"). ``None``/``<= 0`` disables the check
        (byte-identical to pre-AD-1055).
        """
        entries = self.entries()
        now_ts = time.time() if now is None else now
        # AD-1055: drop a stale latest observation (camera effectively off) so
        # the agent gets the explicit no-data sentinel instead of a carried-over
        # scene. Applied before the empty-check so a stale ring renders exactly
        # like an empty one.
        if entries and freshness_s is not None and freshness_s > 0:
            stale_age = max(0.0, now_ts - entries[-1].timestamp)
            if stale_age > freshness_s:
                entries = []
        if not entries:
            return (
                "--- Current Visual Context ---\n"
                "Camera not active or no frames described yet. "
                "Do NOT describe what you cannot see.\n"
                "--- End Visual Context ---"
            )

        latest = entries[-1]
        age_s = max(0.0, now_ts - latest.timestamp)
        age_str = _format_age(age_s)

        lines = [
            "--- Current Visual Context ---",
            _VISUAL_DISPOSITION,
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

    def decayed_novelty(
        self,
        *,
        alpha: float = 0.3,
        now: float | None = None,
        freshness_s: float | None = None,
    ) -> float:
        """AD-1060: an exponential moving average of recent observation novelty.

        Folded oldest->newest with weight ``alpha`` on each newer frame, so a
        sustained run of low-novelty (stable-scene) frames decays toward 0 while
        a recent spike pulls it back up. The router uses this to taper visual
        injection FREQUENCY — once the decayed novelty falls below a threshold
        the scene has settled into the background and injection is suppressed
        (a raw-novelty spike still injects immediately, independent of this).

        Returns 0.0 for an empty ring, or for a stale ring when ``freshness_s``
        is set (a camera-off scene has no current novelty — the AD-1055 rule).
        """
        entries = self.entries()
        if entries and freshness_s is not None and freshness_s > 0:
            now_ts = time.time() if now is None else now
            if max(0.0, now_ts - entries[-1].timestamp) > freshness_s:
                return 0.0
        if not entries:
            return 0.0
        ema = entries[0].novelty_score
        for obs in entries[1:]:
            ema = alpha * obs.novelty_score + (1.0 - alpha) * ema
        return ema


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds // 3600)}h"


# BF-622: the visual-context block (built by ``render_for_prompt`` above) is
# prepended to the LLM INPUT so an agent can describe what it sees. It must
# NEVER appear in a stored/displayed REPLY. It leaked once when a degraded LLM
# proxy echoed its own input prompt back as the completion. This regex removes
# that delimited block (and any leading/trailing blank line it leaves) from a
# reply before persist — defense-in-depth so a prompt-echo can never surface
# internal scaffolding to the chat. The delimiters are the exact strings
# ``render_for_prompt`` emits (single source of truth).
_VISUAL_CONTEXT_BLOCK_RE = re.compile(
    r"-{3} Current Visual Context -{3}.*?-{3} End Visual Context -{3}\n?",
    re.DOTALL,
)


def strip_visual_context_block(text: str) -> str:
    """BF-622: remove any ``--- Current Visual Context --- … --- End Visual
    Context ---`` span from ``text``.

    Conservative: only the exact delimited block(s) are removed; all normal
    prose is left intact. Returns the text with the block(s) gone and
    surrounding whitespace trimmed. A non-string input returns ``""``.
    Callers should treat an emptied result (the whole "reply" was echoed
    scaffolding) as a non-reply.
    """
    if not isinstance(text, str) or not text:
        return ""
    return _VISUAL_CONTEXT_BLOCK_RE.sub("", text).strip()


__all__ = ["VisionWorkingMemory", "VisionObservation", "strip_visual_context_block"]
