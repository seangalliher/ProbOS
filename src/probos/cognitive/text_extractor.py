"""AD-720d (Wave 139): non-image attachment text extraction.

stdlib-only. PDF / DOCX / XLSX extraction is deferred to AD-720a-1.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


_TEXT_PASSTHROUGH_MIMES: frozenset[str] = frozenset({
    "text/plain",
    "text/markdown",
    "text/csv",
})


async def extract_text(
    blob: bytes,
    mime: str,
    *,
    max_bytes: int,
) -> tuple[str, bool]:
    """Return ``(extracted_text, was_truncated)`` for non-image attachment bytes.

    Branches:
      - text/plain | text/markdown | text/csv: ``blob.decode("utf-8", errors="strict")``
        (CSV is passed through as-is — the LLM reasons over CSV natively).
      - application/json: ``json.dumps(json.loads(blob.decode("utf-8")), indent=2)``
        (pretty-printed for the LLM).
      - application/pdf: raises
        ``NotImplementedError("AD-720a-1: PDF extraction not yet wired")``.

    Truncation: if the extracted text's UTF-8 byte length exceeds ``max_bytes``,
    truncate at the byte boundary (decode-safe via
    ``text.encode()[:max_bytes].decode("utf-8", errors="ignore")``) and append
    ``\\n[TRUNCATED]``. Returns ``was_truncated=True`` in that case.

    Unknown MIME: raises ``ValueError(f"unsupported MIME for text extraction: {mime!r}")``.
    """
    if mime == "application/pdf":
        raise NotImplementedError("AD-720a-1: PDF extraction not yet wired")

    if mime in _TEXT_PASSTHROUGH_MIMES:
        text = blob.decode("utf-8", errors="strict")
    elif mime == "application/json":
        parsed = json.loads(blob.decode("utf-8", errors="strict"))
        text = json.dumps(parsed, indent=2)
    else:
        raise ValueError(f"unsupported MIME for text extraction: {mime!r}")

    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
        return (truncated + "\n[TRUNCATED]", True)
    return (text, False)
