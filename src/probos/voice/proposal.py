"""AD-718a: hardened parser for agent-authored voice proposals.

Mirrors the AD-721d ``_parse_appearance_dsl`` pipeline byte-for-byte:
size cap → anchor/alias/tag reject → ``yaml.safe_load`` → depth guard →
:class:`VoiceProfile` construction (which re-runs ``__post_init__`` bounds).

The :class:`VoiceProfile` dataclass is the **single source of bounds
truth**; this parser does not duplicate the bounds checks. Per the
Wave 136 dispatch, no Pydantic ``VoiceProposal`` model is introduced;
``VoiceProfile.__post_init__`` validates every approved-from-proposal
flow.

NEVER calls ``exec``/``eval``/``compile``/``importlib.import_module``/
``pickle.loads`` on the LLM-derived artifact.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from probos.crew_profile import VoiceProfile


# Hard size cap on raw LLM output before any parser sees it.
_MAX_PROPOSAL_BYTES = 16 * 1024
# Defense-in-depth guard against parser-resource attacks.
_MAX_DEPTH = 8
# Trim agent rationale to a sensible UI-facing size.
_MAX_RATIONALE_CHARS = 500
# Allowed top-level keys in the parsed dict.
_ALLOWED_KEYS = {"voice_name", "pitch", "rate", "volume", "rationale", "wake_phrase"}
# Voice-profile fields forwarded to :class:`VoiceProfile`.
_PROFILE_KEYS = ("voice_name", "pitch", "rate", "volume", "wake_phrase")


class VoiceProposalError(Exception):
    """Raised when an LLM voice-proposal response fails parsing or validation.

    Always carries a structured ``reason`` so the caller can surface a typed
    error to the Captain instead of a free-form string.
    """

    def __init__(self, reason: str, *, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def _max_depth(obj: Any, depth: int = 1) -> int:
    """Return the maximum nesting depth of a JSON-like Python object."""
    if isinstance(obj, dict):
        if not obj:
            return depth
        return max(_max_depth(v, depth + 1) for v in obj.values())
    if isinstance(obj, list):
        if not obj:
            return depth
        return max(_max_depth(v, depth + 1) for v in obj)
    return depth


def parse_voice_proposal(text: str) -> tuple[VoiceProfile, str]:
    """Parse an LLM voice-proposal response into ``(VoiceProfile, rationale)``.

    Args:
        text: Raw LLM response. Expected to be strict JSON matching the
            voice-proposal schema (see AD-718a prompt §6 D1).

    Returns:
        Tuple of (validated ``VoiceProfile``, rationale string ≤
        ``_MAX_RATIONALE_CHARS``).

    Raises:
        VoiceProposalError: response oversized, contained YAML
            anchor/alias/tag tokens, exceeded depth bounds, did not
            decode to a top-level dict, contained unknown keys, or
            failed :class:`VoiceProfile` bounds validation.
    """
    # 1. Size cap (bytes — hostile inputs may use multi-byte).
    encoded = text.encode("utf-8")
    if len(encoded) > _MAX_PROPOSAL_BYTES:
        raise VoiceProposalError(
            "response_oversized",
            detail=f"{len(encoded)} bytes > {_MAX_PROPOSAL_BYTES}",
        )

    # 2. Reject YAML anchors / aliases / tag tokens at the byte level.
    #    JSON does not use these; rejecting blocks alias-bomb fan-out.
    if "&" in text or "!!" in text or re.search(r"(?<!\\)\*[A-Za-z_]", text):
        raise VoiceProposalError(
            "yaml_anchor_or_alias",
            detail="response contains YAML anchor/alias/tag markers",
        )

    # 3. Strip an optional Markdown fence the model may emit.
    stripped = text
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*\n", "", stripped)
        stripped = re.sub(r"\n```\s*$", "", stripped)

    # 4. yaml.safe_load — JSON is a YAML subset; safe_load blocks tag execution.
    try:
        parsed = yaml.safe_load(stripped)
    except yaml.YAMLError as exc:
        raise VoiceProposalError("parse_error", detail=str(exc)) from exc
    if not isinstance(parsed, dict):
        raise VoiceProposalError(
            "parse_error",
            detail=f"expected JSON object at top level, got {type(parsed).__name__}",
        )

    # 5. Depth guard.
    if _max_depth(parsed) > _MAX_DEPTH:
        raise VoiceProposalError(
            "depth_exceeded",
            detail=f"document nests > {_MAX_DEPTH} levels",
        )

    # 6. Reject unknown keys (defense-in-depth: caller may have accidentally
    #    passed a richer schema).
    for key in parsed:
        if key not in _ALLOWED_KEYS:
            raise VoiceProposalError(
                "unknown_key",
                detail=f"unknown key: {key}",
            )

    # 7. Construct VoiceProfile — __post_init__ re-runs all bounds.
    profile_kwargs = {k: parsed[k] for k in _PROFILE_KEYS if k in parsed}
    try:
        profile = VoiceProfile(**profile_kwargs)
    except (TypeError, ValueError) as exc:
        raise VoiceProposalError("schema_violation", detail=str(exc)) from exc

    rationale_raw = parsed.get("rationale", "")
    if not isinstance(rationale_raw, str):
        raise VoiceProposalError(
            "schema_violation",
            detail=f"rationale must be a string, got {type(rationale_raw).__name__}",
        )
    rationale = rationale_raw[:_MAX_RATIONALE_CHARS]

    return profile, rationale


__all__ = [
    "VoiceProposalError",
    "parse_voice_proposal",
]
