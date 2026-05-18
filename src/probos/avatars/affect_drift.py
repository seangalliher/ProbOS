"""AD-740: affect-vs-intent drift trend summariser.

Pure read-only summarisation of the AD-722a-5 ring buffer
(``runtime.divergence_history``). No new data capture, no LLM call, no
side effects. Honest-degrade when the buffer is absent or below the
``_MIN_SAMPLES`` floor.

Closes GH issue #664 (Ezri-requested trend depth for the AD-728d
self-image-awareness skill).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


_MIN_SAMPLES = 2  # Below this, return insufficient_data.


def get_affect_drift(
    runtime: Any,
    agent_id: str,
    *,
    window: int | None = None,
    threshold: float | None = None,
) -> dict[str, Any]:
    """Summarise affect-vs-intent drift over the last ``window`` divergences.

    Reads ``runtime.divergence_history[agent_id]`` (AD-722a-5 ring
    buffer). Returns a flat dict suitable for inclusion in an agent's
    next-prompt PROPRIOCEPTION block. NEVER raises.

    Honest-degrade contract:
      * ``runtime.divergence_history`` absent / not a mapping → insufficient_data.
      * Bucket missing for ``agent_id`` → insufficient_data, samples=0.
      * Fewer than ``_MIN_SAMPLES`` entries in the window → insufficient_data.
    """
    cfg = getattr(getattr(runtime, "config", None), "avatars", None)
    if window is None:
        window = int(getattr(cfg, "affect_drift_default_window", 8))
    if threshold is None:
        threshold = float(getattr(cfg, "affect_drift_threshold", 0.7))
    if window < _MIN_SAMPLES:
        window = _MIN_SAMPLES

    div_history = getattr(runtime, "divergence_history", None)
    if not isinstance(div_history, dict):
        return {"insufficient_data": True, "samples": 0}

    bucket = div_history.get(agent_id)
    if bucket is None:
        return {"insufficient_data": True, "samples": 0}

    try:
        entries = list(bucket)[-window:]
    except Exception:
        logger.warning(
            "AD-740: divergence_history bucket for agent=%s not iterable; "
            "returning insufficient_data",
            agent_id, exc_info=True,
        )
        return {"insufficient_data": True, "samples": 0}

    samples = len(entries)
    if samples < _MIN_SAMPLES:
        return {"insufficient_data": True, "samples": samples}

    total = 0.0
    below = 0
    longest = 0
    current_streak = 0
    for entry in entries:
        score = float(getattr(getattr(entry, "result", None), "match_score", 1.0))
        total += score
        if score < threshold:
            below += 1
            current_streak += 1
            if current_streak > longest:
                longest = current_streak
        else:
            current_streak = 0

    return {
        "window": window,
        "samples": samples,
        "mean_match_score": total / samples,
        "below_threshold_count": below,
        "longest_divergent_streak": longest,
        "threshold": threshold,
    }
