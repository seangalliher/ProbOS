"""AD-739: Captain Card — operator self-card, always-in-context.

Wave 163 ships the data model + storage + rendering + validation pipeline.
Prompt-builder injection point and Dreaming-loop integration are deferred
to forward markers AD-739-prompt-wire and AD-739-dreaming-wire respectively.

The Card is system-maintained — NOT agent-self-edited. Updates flow through
Dreaming consolidation and correction-feedback only. The render path is
pure-template; no LLM call.

AD-731 invariant: ``avatar_ref`` is a SHA-256 string when set (validated by
Pydantic), never inline bytes.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import BaseModel, Field, field_validator

# AD-739 reuses the AD-588/589/592 confabulation guard regex.
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE

logger = logging.getLogger(__name__)

_SHA256_HEX_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
_lock = RLock()


class CorrectionRef(BaseModel):
    """Reference to one high-importance correction episode."""
    episode_id: str
    summary: str = Field(default="", max_length=200)
    timestamp: float


class CaptainCard(BaseModel):
    """System-maintained operator identity and continuity card."""

    # --- AD-757 Captain Card Context Bootstrap ---
    id: str = Field(default_factory=lambda: "captain-card-uuid")
    name: str = Field(default="Captain")
    email: str | None = None
    preferred_work_hours: str = Field(default="08:00-18:00")
    timezone: str = Field(default="UTC")
    voice_profile: str | None = None
    avatar_theme: str = Field(default="default")
    last_active_session: float | None = None
    continuity_checksum: str = Field(
        default="",
        description="SHA256 of profile for anomaly detection",
    )

    # Existing AD-739 fields
    callsign: str | None = None
    role: str = Field(default="Operator")
    tone: str = Field(default="direct")
    formatting_preferences: list[str] = Field(default_factory=list)
    current_project: str | None = None
    current_wave: str | None = None
    preferences: list[str] = Field(default_factory=list, max_length=10)
    recent_corrections: list[CorrectionRef] = Field(default_factory=list, max_length=3)
    avatar_ref: str | None = Field(
        default=None,
        description=(
            "AttachmentStore SHA-256 ref. Reserved for AD-733a "
            "streaming-vision coupling; v1 does not consume."
        ),
    )
    version: int = Field(default=1)
    updated_at: float = Field(default_factory=time.time)

    @field_validator("avatar_ref")
    @classmethod
    def _validate_avatar_ref_is_sha256(cls, v: str | None) -> str | None:
        """AD-731 invariant: avatar_ref MUST be a SHA-256 hex string when set."""
        if v is None or v == "":
            return v
        if not _SHA256_HEX_RE.match(v):
            raise ValueError("avatar_ref must be a 64-character hex SHA-256 string")
        return v

    def to_system_context(self) -> str:
        """Generate system prompt preamble from card for LLM context bootstrap."""
        return (
            f"You are Yeo, {self.name}'s personal assistant.\n"
            f"Working hours: {self.preferred_work_hours} {self.timezone}\n"
            f"Voice: {self.voice_profile or 'Ship\'s Computer'}\n"
            f"Avatar: {self.avatar_theme}\n"
        )


def default_captain_card() -> CaptainCard:
    """Bootstrap default when no Card exists yet."""
    return CaptainCard()


def load_card(path: str | Path) -> CaptainCard:
    """Load the Captain Card from JSON sidecar. Returns default on any failure."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
        data = json.loads(text)
        return CaptainCard.model_validate(data)
    except FileNotFoundError:
        return default_captain_card()
    except (OSError, ValueError, TypeError):
        logger.warning(
            "AD-739: failed to load Captain Card from %s; using default",
            path, exc_info=True,
        )
        return default_captain_card()


def save_card(card: CaptainCard, path: str | Path) -> bool:
    """Persist the Card via atomic temp-file + replace. Returns False on failure."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with _lock:
            tmp.write_text(card.model_dump_json(), encoding="utf-8")
            tmp.replace(p)
        return True
    except OSError:
        logger.warning(
            "AD-739: failed to save Captain Card to %s; degrading", path, exc_info=True,
        )
        return False


def render_card_for_prompt(
    card: CaptainCard,
    *,
    max_tokens: int = 500,
) -> str:
    """Render the Captain Card as a compact prompt block.

    Truncation: when the rendered text exceeds the budget (approximated as
    ``max_tokens * 4`` chars), the ``preferences`` and ``recent_corrections``
    lists are dropped from the tail until the budget fits. Identity fields
    (name, callsign, role) are preserved.

    Validation: AD-588/589/592 confabulation-guard regex
    (``_CAPABILITY_GAP_RE``) is applied to each rendered line; any line
    matching the gap-phrasing pattern is dropped with a logged warning.
    """
    max_chars = max(40, int(max_tokens) * 4)
    preferences = list(card.preferences)
    corrections = list(card.recent_corrections)

    def _render(prefs: list[str], corrs: list[CorrectionRef]) -> str:
        lines: list[str] = [
            "name: " + card.name,
        ]
        if card.callsign:
            lines.append("callsign: " + card.callsign)
        lines.append("role: " + card.role)
        lines.append("tone: " + card.tone)
        if card.current_project:
            lines.append("current_project: " + card.current_project)
        if card.current_wave:
            lines.append("current_wave: " + card.current_wave)
        if card.formatting_preferences:
            lines.append(
                "formatting: " + ", ".join(card.formatting_preferences)
            )
        if prefs:
            lines.append("preferences:")
            for pref in prefs:
                lines.append("  - " + pref)
        if corrs:
            lines.append("recent_corrections:")
            for c in corrs:
                lines.append(f"  - {c.summary}")
        return "\n".join(lines)

    text = _render(preferences, corrections)

    # Truncate from the tail.
    while len(text) > max_chars and corrections:
        corrections.pop()
        text = _render(preferences, corrections)
    while len(text) > max_chars and preferences:
        preferences.pop()
        text = _render(preferences, corrections)

    # AD-588/589/592 confabulation guard — drop lines that match the
    # capability-gap phrasing.
    surviving: list[str] = []
    for line in text.splitlines():
        if _CAPABILITY_GAP_RE.search(line):
            logger.warning(
                "AD-739: rendered Card line matched capability-gap pattern; dropping: %r",
                line,
            )
            continue
        surviving.append(line)
    return "\n".join(surviving)


__all__ = [
    "CaptainCard",
    "CorrectionRef",
    "default_captain_card",
    "load_card",
    "render_card_for_prompt",
    "save_card",
]
