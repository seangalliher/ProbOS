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

What v1 does NOT do:
    * other widget kinds — text input, multi-select, form (AD-811b)
    * group-chat producer (AD-811c)
    * channel adapters — Slack/Teams/etc. (AD-811d)
    * DecisionQueue -> A2UI surfacing (AD-811e)
    * response correlation back to the originating spec (AD-811f)
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

# Schema-level hard cap on the option count, independent of the config
# gate. The config value ``a2ui_max_options`` (default 10) gates more
# tightly at extraction time; this keeps the schema self-contained so it
# is safe to construct/parse anywhere without a config handle.
_MAX_OPTIONS_HARD_CAP = 20
_MAX_PROMPT_LEN = 500


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
        trimmed = (v or "").strip()
        if not trimmed:
            raise ValueError("prompt must be a non-empty string")
        if len(trimmed) > _MAX_PROMPT_LEN:
            raise ValueError(
                f"prompt exceeds the {_MAX_PROMPT_LEN}-char limit"
            )
        return trimmed

    @field_validator("options")
    @classmethod
    def _validate_options(cls, v: list[str]) -> list[str]:
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

    def to_json(self) -> str:
        """Serialize to a compact JSON string (the artifact body)."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str) -> "AgentUIChoiceSpec":
        """Parse + validate a JSON string. Raises on malformed/invalid input."""
        return cls.model_validate_json(raw)
