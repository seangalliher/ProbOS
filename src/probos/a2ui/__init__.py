"""AD-811a: A2UI choice-widget schema (default-OFF).

The ``[A2UI]{json}[/A2UI]`` reply tag lets a Lieutenant+ crew agent emit a
single-choice spec inside a 1:1 DM reply. The DM reply pipeline validates
the spec, stores it as an ``application/json`` artifact (the AD-797
two-call write), and leaves an inline ``[A2UI: name vN - choice]`` stub;
the HXI renders an interactive choice card whose click posts the chosen
option back through the existing ``sendText`` chat route.

This module owns ONLY the schema (:class:`AgentUIChoiceSpec`). It is inert
unless ``CommunicationsConfig.a2ui_enabled`` is True (default False) — with
the flag off no agent is taught the tag and the schema is never exercised
on the live path, so behavior is byte-identical to pre-AD-811a.

What this module does NOT do (AD-811b-1 adds ``form``):
    * other widget kinds — range (AD-811b-2), date (AD-811b-3)
    * group-chat producer (AD-811c)
    * channel adapters — Slack/Teams/etc. (AD-811d)
    * DecisionQueue -> A2UI surfacing (AD-811e)
    * response correlation back to the originating spec (AD-811f)
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Schema-level hard cap on the option count, independent of the config
# gate. The config value ``a2ui_max_options`` (default 10) gates more
# tightly at extraction time; this keeps the schema self-contained so it
# is safe to construct/parse anywhere without a config handle.
_MAX_OPTIONS_HARD_CAP = 20
_MAX_PROMPT_LEN = 500

# AD-811b-1: schema-level hard cap on a form's field count, mirroring
# `_MAX_OPTIONS_HARD_CAP`. The config gate `a2ui_max_options` is
# option-specific and no-ops for forms (the extractor reads `spec.options`,
# which a form lacks), so fields are bounded entirely by the schema.
_MAX_FIELDS = 20


def _clean_prompt(v: str) -> str:
    """Trim + validate a widget prompt (shared by every A2UI spec).

    AD-811b: extracted from ``AgentUIChoiceSpec`` so each widget kind
    delegates to ONE implementation (DRY). Behavior is byte-identical to
    the AD-811a inline validator.
    """
    trimmed = (v or "").strip()
    if not trimmed:
        raise ValueError("prompt must be a non-empty string")
    if len(trimmed) > _MAX_PROMPT_LEN:
        raise ValueError(
            f"prompt exceeds the {_MAX_PROMPT_LEN}-char limit"
        )
    return trimmed


def _clean_options(v: list[str]) -> list[str]:
    """Trim/dedupe/cap a widget option list (shared by every A2UI spec).

    AD-811b: extracted from ``AgentUIChoiceSpec`` so each widget kind
    delegates to ONE implementation (DRY). Drops empties, dedupes (order
    preserved), and enforces the 2..20 bounds — byte-identical to the
    AD-811a inline validator.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in v or []:
        opt = (raw or "").strip()
        if not opt or opt in seen:
            continue
        seen.add(opt)
        cleaned.append(opt)
    if len(cleaned) < 2:
        raise ValueError("a choice spec needs at least 2 distinct options")
    if len(cleaned) > _MAX_OPTIONS_HARD_CAP:
        raise ValueError(
            f"a choice spec accepts at most {_MAX_OPTIONS_HARD_CAP} options"
        )
    return cleaned


class AgentUIChoiceSpec(BaseModel):
    """A single-choice widget spec carried by an ``[A2UI]{json}[/A2UI]`` tag.

    ``prompt`` is the question shown above the buttons; ``options`` is the
    ordered list of choices (2..20 after validation — duplicates dropped,
    empties dropped, order preserved). The schema enforces its own hard
    cap of 20 options regardless of config; the ``a2ui_max_options``
    config value gates more tightly at extraction time.
    """

    kind: Literal["choice"] = "choice"
    prompt: str
    options: list[str]

    @field_validator("prompt")
    @classmethod
    def _validate_prompt(cls, v: str) -> str:
        return _clean_prompt(v)

    @field_validator("options")
    @classmethod
    def _validate_options(cls, v: list[str]) -> list[str]:
        return _clean_options(v)

    def to_json(self) -> str:
        """Serialize to a compact JSON string (the artifact body)."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str) -> "AgentUIChoiceSpec":
        """Parse + validate a JSON string. Raises on malformed/invalid input."""
        return cls.model_validate_json(raw)


class AgentUIMultiSelectSpec(BaseModel):
    """A multi-select widget spec carried by an ``[A2UI]{json}[/A2UI]`` tag.

    AD-811b: the 2nd A2UI widget kind. Like :class:`AgentUIChoiceSpec` but
    the Captain may pick several options at once. ``prompt``/``options``
    share the same validators (the DRY ``_clean_*`` helpers).
    ``min_select``/``max_select`` bound the selection count; the HXI
    returns the picks joined by commas (option order). The schema enforces
    the same 2..20 hard cap on options as the choice spec.
    """

    kind: Literal["multiselect"] = "multiselect"
    prompt: str
    options: list[str]
    min_select: int = Field(default=1, ge=1)
    max_select: int | None = None

    @field_validator("prompt")
    @classmethod
    def _validate_prompt(cls, v: str) -> str:
        return _clean_prompt(v)

    @field_validator("options")
    @classmethod
    def _validate_options(cls, v: list[str]) -> list[str]:
        return _clean_options(v)

    @model_validator(mode="after")
    def _validate_bounds(self) -> "AgentUIMultiSelectSpec":
        """Enforce the selection bounds against the cleaned option count.

        Runs after field validation, so ``self.options`` is already
        trimmed/deduped. ``min_select`` must fit within the options;
        ``max_select`` (when set) must be >= ``min_select`` and is clamped
        down to the option count when it overshoots.
        """
        n = len(self.options)
        if self.min_select > n:
            raise ValueError(
                "min_select cannot exceed the number of options"
            )
        if self.max_select is not None:
            if self.max_select < self.min_select:
                raise ValueError("max_select cannot be less than min_select")
            if self.max_select > n:
                self.max_select = n
        return self

    def to_json(self) -> str:
        """Serialize to a compact JSON string (the artifact body)."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str) -> "AgentUIMultiSelectSpec":
        """Parse + validate a JSON string. Raises on malformed/invalid input."""
        return cls.model_validate_json(raw)


class AgentUIFormField(BaseModel):
    """One labeled free-text input in an :class:`AgentUIFormSpec`.

    AD-811b-1: v1 fields are free text only (no per-field type system —
    that is AD-811b-1a if ever warranted). ``label`` is trimmed here; the
    parent spec drops empty-label fields and dedupes by label (mirroring
    ``_clean_options``). ``required`` gates the card's Submit button.
    """

    label: str
    required: bool = False

    @field_validator("label")
    @classmethod
    def _trim_label(cls, v: str) -> str:
        # Trim only (no raise): the parent spec drops empty labels, mirroring
        # the trim-then-drop behavior of `_clean_options`.
        return (v or "").strip()


class AgentUIFormSpec(BaseModel):
    """A multi-field form widget spec carried by an ``[A2UI]{json}[/A2UI]`` tag.

    AD-811b-1: the 3rd A2UI widget kind. ``prompt`` shares the
    ``_clean_prompt`` validator; ``fields`` is an ordered list of labeled
    free-text inputs (1..``_MAX_FIELDS`` after validation — empty labels
    dropped, deduped by label, order preserved). The HXI renders one text
    input per field and posts the filled values back as ``label: value``
    lines through the existing ``sendText`` chat route.
    """

    kind: Literal["form"] = "form"
    prompt: str
    fields: list[AgentUIFormField]

    @field_validator("prompt")
    @classmethod
    def _validate_prompt(cls, v: str) -> str:
        return _clean_prompt(v)

    @field_validator("fields")
    @classmethod
    def _validate_fields(
        cls, v: list[AgentUIFormField]
    ) -> list[AgentUIFormField]:
        cleaned: list[AgentUIFormField] = []
        seen: set[str] = set()
        for f in v or []:
            if not f.label or f.label in seen:
                continue
            seen.add(f.label)
            cleaned.append(f)
        if len(cleaned) < 1:
            raise ValueError("a form spec needs at least 1 field")
        if len(cleaned) > _MAX_FIELDS:
            raise ValueError(
                f"a form spec accepts at most {_MAX_FIELDS} fields"
            )
        return cleaned

    def to_json(self) -> str:
        """Serialize to a compact JSON string (the artifact body)."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str) -> "AgentUIFormSpec":
        """Parse + validate a JSON string. Raises on malformed/invalid input."""
        return cls.model_validate_json(raw)


# --------------------------------------------------------------------------- #
# AD-811b: N-kind dispatch — a ``kind``-keyed registry + a single parse entry  #
# point. Adding a widget kind = register its spec class here. The DM extractor #
# and the HXI both route through this one dispatcher, so the choice path stays #
# byte-identical while new kinds slot in without touching the call sites.      #
# --------------------------------------------------------------------------- #

A2UISpec = AgentUIChoiceSpec | AgentUIMultiSelectSpec | AgentUIFormSpec

_SPEC_BY_KIND: dict[str, type[A2UISpec]] = {
    "choice": AgentUIChoiceSpec,
    "multiselect": AgentUIMultiSelectSpec,
    "form": AgentUIFormSpec,
}


def parse_a2ui_spec(raw: str) -> A2UISpec | None:
    """Parse a raw JSON A2UI body into the spec for its ``kind``.

    Honest-degrade (Tier-2): returns ``None`` on malformed JSON, a
    non-object payload, a missing/non-string/unknown ``kind``, or any
    schema validation failure \u2014 never raises. This is the single N-kind
    entry point; register a new kind in :data:`_SPEC_BY_KIND`.
    """
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    kind = data.get("kind")
    cls = _SPEC_BY_KIND.get(kind) if isinstance(kind, str) else None
    if cls is None:
        return None
    try:
        return cls.model_validate(data)
    except Exception:
        return None
