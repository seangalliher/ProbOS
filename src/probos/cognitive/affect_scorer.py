"""AD-1037 (#986): store-time affective-salience scoring.

Assigns a [0,1] affective-salience score to an episode at encoding time from an
arousal/affect *lexicon* — the MAGNITUDE of emotional charge, not valence. Pure
heuristic: no LLM, no network (``EpisodicMemory.store()`` is hot).

Populates the AD-979f ``Episode.affect_salience`` slot, which the AD-873
composite reranker's affect term consumes (default weight ``0.0`` -> skipped, so
the populator is byte-identical until an operator opts in). Orthogonal to
AD-598 ``importance`` (importance keys on trigger_type/channel/outcome —
retention priority; affect keys on arousal vocabulary — emotional charge).

Mirrors the AD-598 ``importance_scorer`` shape: a single pure function wrapped
in try/except that degrades to a neutral default (0.0).
"""

from __future__ import annotations

import logging
import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.types import Episode

logger = logging.getLogger(__name__)

# Normalization time-constant for the raw -> [0,1] map ``1 - exp(-raw/TAU)``.
# Larger TAU = gentler saturation (more raw signal needed to approach 1.0).
_TAU = 2.0

# High-arousal vocabulary. Each hit contributes 1.0 to ``raw``. DD-3: magnitude,
# not valence — both positive ("thrilled") and negative ("devastated") words
# raise salience. Disjoint from ``_MODERATE_AROUSAL``.
_HIGH_AROUSAL: frozenset[str] = frozenset({
    "thrilled", "ecstatic", "elated", "overjoyed", "devastated", "furious",
    "enraged", "terrified", "panicked", "panic", "alarmed", "horrified",
    "outraged", "frantic", "desperate", "crisis", "emergency", "urgent",
    "critical", "catastrophe", "breakthrough", "amazing", "incredible",
    "shocking", "terrible", "awful", "disaster",
})

# Moderate-arousal vocabulary. Each hit contributes 0.5 to ``raw``. Disjoint
# from ``_HIGH_AROUSAL`` (a word charged enough to be "high" is never "moderate").
_MODERATE_AROUSAL: frozenset[str] = frozenset({
    "worried", "anxious", "nervous", "concerned", "excited", "happy", "glad",
    "pleased", "sad", "unhappy", "angry", "annoyed", "frustrated", "afraid",
    "scared", "relieved", "grateful", "proud", "disappointed", "upset",
    "surprised", "confused", "hopeful", "eager", "fear", "joy",
})


def score_affect(episode: "Episode") -> float:
    """Compute affective-salience [0,1] for an episode at encoding time.

    Reads the episode's user + agent text (``user_input`` + ``reflection``) and
    scores the MAGNITUDE of emotional charge (DD-3): both "thrilled" and
    "devastated" contribute positively. Deterministic, no I/O.

    ``raw = 1.0*high_hits + 0.5*moderate_hits + exclam_bonus + caps_bonus`` where
    ``exclam_bonus = min(0.5, 0.1 * text.count("!"))`` and
    ``caps_bonus = min(0.5, 0.25 * (# of ALL-CAPS alpha tokens, len>=3))``.
    Token-multiset counting (repeats count). ``affect_salience =
    clamp01(1 - exp(-raw/TAU))``; ``raw == 0`` -> exactly ``0.0``.

    Returns 0.0 (neutral) when no arousal signal is present or on any error.
    """
    try:
        text = (episode.user_input or "") + " " + (episode.reflection or "")
        lowered = text.lower()
        tokens = re.findall(r"[a-z']+", lowered)
        high_hits = sum(1 for t in tokens if t in _HIGH_AROUSAL)
        moderate_hits = sum(1 for t in tokens if t in _MODERATE_AROUSAL)
        # Emphasis bonuses, each capped so punctuation/caps can't swamp lexicon.
        exclam_bonus = min(0.5, 0.1 * text.count("!"))
        caps = [
            w for w in re.findall(r"[A-Za-z]+", text)
            if w.isupper() and len(w) >= 3
        ]
        caps_bonus = min(0.5, 0.25 * len(caps))
        raw = 1.0 * high_hits + 0.5 * moderate_hits + exclam_bonus + caps_bonus
        if raw <= 0.0:
            return 0.0  # DD-5: raw == 0 -> exactly 0.0 (neutral, no charge)
        value = 1.0 - math.exp(-raw / _TAU)
        # Clamp defensively into [0,1] (the map is already bounded, but caps).
        if value < 0.0:
            return 0.0
        if value > 1.0:
            return 1.0
        return value
    except Exception:
        logger.debug(
            "AD-1037: affect scoring failed; defaulting to 0.0", exc_info=True
        )
        return 0.0
