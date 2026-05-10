"""AD-720: defense-in-depth MIME validator. stdlib-only, no libmagic.

Why not ``imghdr``: deprecated in Python 3.11 and removed in 3.13. Magic-byte
sniffing here is the primary correctness signal; it does not depend on
``imghdr`` being importable.
"""

from __future__ import annotations


# Magic-byte signatures for the four allowed MIMEs.
# Each entry: list of (offset, signature_bytes) tuples — ALL must match.
_SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
    "image/png":  [(0, b"\x89PNG\r\n\x1a\n")],
    "image/jpeg": [(0, b"\xff\xd8\xff")],
    "image/gif":  [(0, b"GIF87a"), (0, b"GIF89a")],   # either alternative
    "image/webp": [(0, b"RIFF"), (8, b"WEBP")],       # both required
}

# MIMEs whose sigs are alternatives (any-of) instead of conjunctions (all-of).
_ANY_OF: frozenset[str] = frozenset({"image/gif"})


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
