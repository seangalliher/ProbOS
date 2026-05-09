"""AD-721d: `AvatarDSL` — agent-authored appearance artifact (data, not code).

The agent reflects on its personality and proposes a structured `AvatarDSL`
artifact. The Captain reviews and approves; the approved DSL persists on
``AppearanceProfile.dsl`` (see ``crew_profile.py``). The renderer (AD-721i)
consumes the DSL out-of-band to produce a ``.vrm``. When the renderer is
absent, the DSL is preserved and ``CrewVRM`` falls back to parametric until
an operator runs the renderer.

The DSL is **data**: YAML/JSON serialisable, all fields constrained to typed
enums or numeric bounds, defaults provided everywhere so ``AvatarDSL()`` with
no arguments succeeds. There is NO code execution path for any DSL value at
any layer — ``exec``/``eval``/``compile``/``importlib.import_module`` are
forbidden in this module and in any consumer that reads DSL bytes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Allowed-enum helpers ────────────────────────────────────────────────

BodyType = Literal["slim", "average", "stocky"]
HairStyle = Literal["short", "medium", "long", "ponytail", "bun", "shaved"]
JawShape = Literal["soft", "neutral", "strong"]
EyeShape = Literal["round", "almond", "narrow"]
OutfitStyle = Literal["uniform", "casual", "formal", "robe", "tactical"]
RestingExpression = Literal["neutral", "gentle_smile", "focused", "alert"]


_HEX_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"


# ── Sub-models ──────────────────────────────────────────────────────────


class AvatarBody(BaseModel):
    """Body type and height parameters."""

    model_config = ConfigDict(extra="forbid")

    type: BodyType = "average"
    height_cm: int = 170

    @field_validator("height_cm")
    @classmethod
    def _bound_height(cls, v: int) -> int:
        if not 140 <= v <= 210:
            raise ValueError(f"height_cm must be 140 ≤ x ≤ 210, got {v}")
        return v


class AvatarHair(BaseModel):
    """Hair style and HSL colour."""

    model_config = ConfigDict(extra="forbid")

    style: HairStyle = "medium"
    color_hsl: tuple[int, int, int] = (30, 40, 30)

    @field_validator("color_hsl")
    @classmethod
    def _bound_hsl(cls, v: tuple[int, int, int]) -> tuple[int, int, int]:
        h, s, l = v
        if not 0 <= h <= 360:
            raise ValueError(f"hue must be 0–360, got {h}")
        if not 0 <= s <= 100:
            raise ValueError(f"saturation must be 0–100, got {s}")
        if not 0 <= l <= 100:
            raise ValueError(f"lightness must be 0–100, got {l}")
        return v


class AvatarFace(BaseModel):
    """Face warmth, jawline, eye shape."""

    model_config = ConfigDict(extra="forbid")

    warmth: float = 0.5
    jaw: JawShape = "neutral"
    eyes: EyeShape = "almond"

    @field_validator("warmth")
    @classmethod
    def _bound_warmth(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"warmth must be 0.0–1.0, got {v}")
        return v


class AvatarOutfit(BaseModel):
    """Outfit style + primary colour + up to 4 accent colours."""

    model_config = ConfigDict(extra="forbid")

    style: OutfitStyle = "uniform"
    primary_color: str = Field(default="#2a4a6a", pattern=_HEX_COLOR_PATTERN)
    accents: list[str] = Field(default_factory=list)

    @field_validator("accents")
    @classmethod
    def _bound_accents(cls, v: list[str]) -> list[str]:
        if len(v) > 4:
            raise ValueError(f"outfit.accents may have at most 4 entries, got {len(v)}")
        import re
        for entry in v:
            if not re.match(_HEX_COLOR_PATTERN, entry):
                raise ValueError(f"outfit.accents entry {entry!r} is not a 6-digit hex colour")
        return v


# ── Top-level DSL ───────────────────────────────────────────────────────


class AvatarDSL(BaseModel):
    """Agent-authored appearance artifact.

    All fields default — ``AvatarDSL()`` MUST succeed. This is the
    persistence contract: the schema is forwards-compatible only by adding
    new optional fields with defaults.
    """

    model_config = ConfigDict(extra="forbid")

    body: AvatarBody = Field(default_factory=AvatarBody)
    hair: AvatarHair = Field(default_factory=AvatarHair)
    face: AvatarFace = Field(default_factory=AvatarFace)
    outfit: AvatarOutfit = Field(default_factory=AvatarOutfit)
    expression_resting: RestingExpression = "neutral"
    notes: str = ""

    @field_validator("notes")
    @classmethod
    def _bound_notes(cls, v: str) -> str:
        if len(v) > 280:
            raise ValueError(f"notes must be ≤ 280 chars, got {len(v)}")
        return v


# ── Errors ──────────────────────────────────────────────────────────────


class AppearanceProposalError(Exception):
    """Raised when an agent's DSL proposal fails validation, parsing, or LLM call.

    Always carries a structured ``reason`` so the caller can surface a typed
    error to the Captain instead of a free-form string.
    """

    def __init__(self, reason: str, *, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


__all__ = [
    "AppearanceProposalError",
    "AvatarBody",
    "AvatarDSL",
    "AvatarFace",
    "AvatarHair",
    "AvatarOutfit",
    "BodyType",
    "EyeShape",
    "HairStyle",
    "JawShape",
    "OutfitStyle",
    "RestingExpression",
]
