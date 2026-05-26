"""AD-809: personality registry — named register/style overlays.

These are NOT identity replacements. They are register knobs the Captain
can flip per thread to ask an agent to adopt a particular voice (more
concise, more formal, etc.). The agent's underlying identity (callsign,
crew role, persistent memory, trust state) is unchanged.

The default registry ships with 5 entries derived from common
operator-facing styles. Operators can add more via config (forward
marker AD-809a) — v1 ships the fixed registry.
"""

from __future__ import annotations

# Personality fragments append to the agent's existing system prompt.
# They are written as overlays — short, additive, never absolute.
_REGISTRY: dict[str, str] = {
    "concise": (
        "For this conversation, default to short answers. Aim for 1-3 sentences "
        "unless the Captain explicitly asks for depth."
    ),
    "formal": (
        "For this conversation, use formal register. Address the Captain as "
        "'Captain' rather than by callsign familiarity. Avoid contractions."
    ),
    "socratic": (
        "For this conversation, favor questions over assertions when the topic "
        "permits. Help the Captain think through the problem rather than handing "
        "over a final answer first."
    ),
    "expert": (
        "For this conversation, write at expert-to-expert technical register. "
        "Skip introductions; assume the Captain has the background context. "
        "Cite specific mechanisms, terms of art, and trade-offs."
    ),
    "casual": (
        "For this conversation, drop into a relaxed, conversational register. "
        "Contractions and asides are fine. Keep it human."
    ),
}


def list_personalities() -> list[str]:
    """Return the names of all available personalities."""
    return sorted(_REGISTRY.keys())


def resolve_personality_text(name: str) -> str | None:
    """Resolve a personality name to its registry fragment, or None if unknown."""
    return _REGISTRY.get(name.strip().lower())
