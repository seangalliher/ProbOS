"""AD-720: defense-in-depth MIME validator. stdlib-only, no libmagic.

Why not ``imghdr``: deprecated in Python 3.11 and removed in 3.13. Magic-byte
sniffing here is the primary correctness signal; it does not depend on
``imghdr`` being importable.
"""

from __future__ import annotations

import csv
import io
import json


# Magic-byte signatures for the allowed binary MIMEs.
# Each entry: list of (offset, signature_bytes) tuples — ALL must match
# unless the MIME is in ``_ANY_OF`` (any-of alternative match).
_SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
    "image/png":  [(0, b"\x89PNG\r\n\x1a\n")],
    "image/jpeg": [(0, b"\xff\xd8\xff")],
    "image/gif":  [(0, b"GIF87a"), (0, b"GIF89a")],   # either alternative
    "image/webp": [(0, b"RIFF"), (8, b"WEBP")],       # both required
    # AD-721b-1 (Wave 155): browser-captured utterance audio for the
    # rhubarb-lip-sync backend. WebM containers begin with the EBML magic
    # (\x1a\x45\xdf\xa3); WAV files share RIFF with WebP but with WAVE at
    # offset 8 (rhubarb-lip-sync supports WAV natively).
    "audio/webm": [(0, b"\x1a\x45\xdf\xa3")],
    "audio/wav":  [(0, b"RIFF"), (8, b"WAVE")],       # both required
    # AD-720e (Wave 159): playback-only audio attachments. Multi-option
    # signatures (MP3 sync bytes, MP4 ftyp brands) use the existing
    # _ANY_OF mechanism below.
    "audio/mpeg": [
        (0, b"ID3"),                # MP3 with ID3v2 tag (most common)
        (0, b"\xff\xfb"),            # MP3 frame sync (MPEG-1 Layer 3, no ID3)
        (0, b"\xff\xf3"),            # MP3 frame sync (MPEG-2 Layer 3)
        (0, b"\xff\xf2"),            # MP3 frame sync (MPEG-2.5 Layer 3)
    ],
    "audio/mp4": [
        (4, b"ftypM4A "),            # M4A (most common form)
        (4, b"ftypmp42"),            # MP4 brand mp42
        (4, b"ftypisom"),            # MP4 brand isom
    ],
    "audio/ogg": [
        (0, b"OggS"),                # Ogg container (any codec)
    ],
    # BF-643: Office OOXML deliverables are ZIP containers (PK\x03\x04). One
    # ZIP magic distinguishes them from text/image; the byte-identical magic
    # across docx/xlsx/pptx is acceptable — the allow-list + extension carry
    # the type. Agents produce .docx via the AD-1064/code-exec path.
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":   [(0, b"PK\x03\x04")],
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":         [(0, b"PK\x03\x04")],
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": [(0, b"PK\x03\x04")],
}

# MIMEs whose sigs are alternatives (any-of) instead of conjunctions (all-of).
# AD-720e (Wave 159): MP3 sync bytes (4 variants) and MP4 ftyp brands (3
# variants) are genuine any-of alternatives at the same offset. WAV stays
# out — its (RIFF, WAVE) pair are BOTH required for a valid file.
_ANY_OF: frozenset[str] = frozenset({"image/gif", "audio/mpeg", "audio/mp4"})


def validate_image_bytes(blob: bytes, declared_mime: str) -> tuple[bool, str]:
    """Return ``(True, sniffed_mime)`` if ``blob``'s magic bytes match.

    Returns ``(False, reason)`` otherwise. ``reason`` is one of:
    ``"unknown_declared_mime"``, ``"header_mismatch"``, ``"blob_too_short"``.
    """
    if declared_mime not in _SIGNATURES:
        return (False, "unknown_declared_mime")
    sigs = _SIGNATURES[declared_mime]
    # Length-precondition check.
    for offset, sig in sigs:
        if len(blob) < offset + len(sig):
            return (False, "blob_too_short")
    if declared_mime in _ANY_OF:
        # Any one alternative satisfies.
        for offset, sig in sigs:
            if blob[offset:offset + len(sig)] == sig:
                return (True, declared_mime)
        return (False, "header_mismatch")
    # All signatures must match.
    for offset, sig in sigs:
        if blob[offset:offset + len(sig)] != sig:
            return (False, "header_mismatch")
    return (True, declared_mime)


# AD-720a (Wave 139): non-image attachment validator.

_PDF_MAGIC: bytes = b"%PDF-"
_TEXT_EXTENSIONS: dict[str, frozenset[str]] = {
    "text/plain":    frozenset({".txt"}),
    "text/markdown": frozenset({".md"}),
}
_NON_IMAGE_MIMES: frozenset[str] = frozenset({
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/json",
    "text/csv",
})


def validate_attachment_bytes(
    blob: bytes,
    declared_mime: str,
    declared_filename: str | None = None,
) -> tuple[bool, str]:
    """AD-720a: defense-in-depth validator for the 9 allowed MIMEs.

    Image MIMEs delegate to :func:`validate_image_bytes` (no duplication).
    Non-image MIMEs each have their own magic-byte / parse-attempt / extension
    check. **Strict UTF-8 only** — ``errors='replace'`` is forbidden.

    Returns ``(True, declared_mime)`` on success or ``(False, reason)`` where
    ``reason`` is one of: ``"unknown_declared_mime"``, ``"header_mismatch"``,
    ``"blob_too_short"``, ``"utf8_decode_error"``, ``"json_parse_error"``,
    ``"csv_parse_error"``, ``"extension_mismatch"``.
    """
    # Image MIMEs: delegate verbatim.
    if declared_mime in _SIGNATURES:
        return validate_image_bytes(blob, declared_mime)

    if declared_mime not in _NON_IMAGE_MIMES:
        return (False, "unknown_declared_mime")

    if declared_mime == "application/pdf":
        if len(blob) < len(_PDF_MAGIC):
            return (False, "blob_too_short")
        if blob[: len(_PDF_MAGIC)] != _PDF_MAGIC:
            return (False, "header_mismatch")
        return (True, declared_mime)

    if declared_mime == "application/json":
        try:
            text = blob.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return (False, "utf8_decode_error")
        try:
            json.loads(text)
        except json.JSONDecodeError:
            return (False, "json_parse_error")
        return (True, declared_mime)

    if declared_mime == "text/csv":
        try:
            head = blob[:4096].decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return (False, "utf8_decode_error")
        try:
            reader = csv.reader(io.StringIO(head))
            first = next(reader)
        except (csv.Error, StopIteration):
            return (False, "csv_parse_error")
        if not first:
            return (False, "csv_parse_error")
        return (True, declared_mime)

    # text/plain or text/markdown: three conditions — UTF-8 strict + extension match.
    if declared_mime in _TEXT_EXTENSIONS:
        try:
            blob.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return (False, "utf8_decode_error")
        allowed_exts = _TEXT_EXTENSIONS[declared_mime]
        if not declared_filename:
            return (False, "extension_mismatch")
        lowered = declared_filename.lower()
        if not any(lowered.endswith(ext) for ext in allowed_exts):
            return (False, "extension_mismatch")
        return (True, declared_mime)

    # Defensive — should be unreachable given _NON_IMAGE_MIMES check above.
    return (False, "unknown_declared_mime")
