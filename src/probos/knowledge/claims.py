"""The normalized publish_finding claim core and its publication observation."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

MAX_TITLE_CHARS = 200
MAX_BASIS_CHARS = 1000
MAX_SLUG_CHARS = 48


def finding_slug(title: str) -> str:
    """Use the existing notebook slug spelling without changing claim identity."""
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").strip().lower()).strip("-")
    return slug[:MAX_SLUG_CHARS]


def compute_claim_id(title: str, claim: str, basis: str) -> str:
    """Hash the original publication's canonical, non-ASCII-escaped triple."""
    canonical = json.dumps(
        {"title": title, "claim": claim, "basis": basis},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class FindingClaim(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    title: str
    claim: str
    basis: str
    confidence: float = 0.5

    # Normalization must not narrow the original publisher's accepted strings.
    @field_validator("title", "claim", "basis", mode="plain")
    @classmethod
    def normalize_text(cls, value: Any, info: ValidationInfo) -> str:
        if type(value) is not str:
            raise ValueError("claim text must be a string")
        value = value.strip()
        limits = {"title": MAX_TITLE_CHARS, "basis": MAX_BASIS_CHARS}
        if info.context is not None and "max_content_chars" in info.context:
            limits["claim"] = info.context["max_content_chars"]
        limit = limits.get(info.field_name)
        if not value or (limit is not None and len(value) > limit):
            raise ValueError("claim text is empty or exceeds its publication bound")
        if info.field_name == "title" and not finding_slug(value):
            raise ValueError("claim title has no addressable slug")
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: Any) -> float:
        if type(value) is int:
            value = float(value)
        if type(value) is not float or not 0.0 <= value <= 1.0:
            raise ValueError("claim confidence must be finite and between zero and one")
        return value


class FindingPublication(BaseModel):
    """An observation minted only after the records write has succeeded."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    claim: FindingClaim
    claim_id: str
    path: str
    classification: Literal["private", "department", "ship"]
    requested_scope: Literal["private", "department", "ship", "fleet"]

    @model_validator(mode="after")
    def validate_publication(self) -> FindingPublication:
        expected = compute_claim_id(self.claim.title, self.claim.claim, self.claim.basis)
        if self.claim_id != expected:
            raise ValueError("publication identity differs from its unchanged claim")
        written = "ship" if self.requested_scope == "fleet" else self.requested_scope
        if self.classification != written:
            raise ValueError("publication classification differs from its written scope")
        return self
