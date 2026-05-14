"""AD-738e-1 — Per-emotion Piper prosody overrides (Wave 158).

Bridges the AD-737 emotion taxonomy into AD-738e's prosody knobs. The
override table is partial — emotions not present get NO override and
PiperBackend keeps its constructor defaults (additive guarantee: no
regression of existing behaviour for utterances without an emotion).

Custom emotions (AD-737) are resolved to v1 parents BEFORE reaching this
module — see ``routers/agents.py`` chat-response wiring.
"""

from __future__ import annotations

from typing import Final


# AD-738e-1 partial override table. Keys are ``EmotionalIntent`` string
# values (lowercase). Values are partial dicts: only the prosody knobs
# that DIFFER from PiperBackend constructor defaults are listed.
# Captain Decision (2026-05-13): bias toward expressiveness for warm-
# class emotions, brevity for excited, dryness for formal.
_EMOTION_PROSODY_OVERRIDES: Final[dict[str, dict[str, float]]] = {
    "concerned": {"noise_scale": 0.95, "length_scale": 1.05},
    "excited":   {"noise_scale": 0.95, "length_scale": 0.92},
    "formal":    {"noise_scale": 0.70, "length_scale": 1.0},
    # ``neutral`` is intentionally absent — keep PiperBackend defaults.
    # Future tuning: ``warm`` / ``apologetic`` / ``playful`` / ``reassuring``
    # may add entries; tracked as forward marker AD-738e-2.
}


def resolve_prosody_overrides(emotion: str | None) -> dict[str, float]:
    """Return per-emotion prosody overrides, or ``{}`` for no override.

    Tier-2 log-and-degrade: unknown / ``None`` / empty string returns
    ``{}`` (no override). Callers merge the result on top of their
    defaults — the empty case preserves current behaviour exactly.

    Custom AD-737 emotions MUST be resolved to v1 parents before
    calling this helper. The helper itself only knows v1 names.
    """
    if not emotion:
        return {}
    return dict(_EMOTION_PROSODY_OVERRIDES.get(emotion, {}))
