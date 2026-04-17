"""BF-199: Sanitize text before Ward Room posting."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# JSON field signatures from cognitive sub-task chain outputs.
# Reflect: {"output": "...", "revised": ..., "reflection": "..."}
# Evaluate: {"pass": ..., "score": ..., "criteria": ..., "recommendation": "..."}
_CHAIN_JSON_SIGNATURES = ('"output"', '"pass"', '"score"', '"criteria"')


def sanitize_ward_room_text(text: str) -> str:
    """Extract human-readable text from potentially JSON-wrapped chain output.

    Defense-in-depth guard at the Ward Room posting boundary.
    If the text looks like leaked chain JSON, extract the readable
    content. Otherwise return as-is.
    """
    stripped = text.strip()
    if not stripped.startswith("{"):
        return text

    # Quick check: does this look like chain JSON?
    head = stripped[:200]
    if not any(sig in head for sig in _CHAIN_JSON_SIGNATURES):
        return text

    # Attempt extraction
    try:
        from probos.utils.json_extract import extract_json

        parsed = extract_json(stripped)
    except (ValueError, TypeError):
        return text

    if not isinstance(parsed, dict):
        return text

    # Reflect JSON → extract "output"
    if "output" in parsed and isinstance(parsed["output"], str):
        extracted = parsed["output"].strip()
        if extracted:
            logger.warning(
                "BF-199: Extracted text from leaked reflect JSON (%d → %d chars)",
                len(stripped),
                len(extracted),
            )
            return extracted

    # Evaluate JSON → suppress entirely (not human-readable)
    if "pass" in parsed and "score" in parsed:
        logger.warning("BF-199: Suppressed leaked evaluate JSON (%d chars)", len(stripped))
        return ""

    return text
