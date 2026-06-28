"""AD-720: magic-bytes MIME validator tests."""

from __future__ import annotations

from probos.attachments.mime import validate_attachment_bytes, validate_image_bytes


_PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 16
_JPEG = b"\xff\xd8\xff\xe0" + b"x" * 16
_GIF87 = b"GIF87a" + b"x" * 16
_GIF89 = b"GIF89a" + b"x" * 16
_WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"x" * 16
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_DOCX = b"PK\x03\x04" + b"x" * 16


def test_validate_docx_happy_bf643():
    assert validate_attachment_bytes(_DOCX, _DOCX_MIME) == (True, _DOCX_MIME)


def test_validate_docx_header_mismatch_rejected_bf643():
    ok, reason = validate_attachment_bytes(b"not a zip", _DOCX_MIME)
    assert ok is False and reason == "header_mismatch"


def test_validate_png_happy():
    assert validate_image_bytes(_PNG, "image/png") == (True, "image/png")


def test_validate_jpeg_happy():
    assert validate_image_bytes(_JPEG, "image/jpeg") == (True, "image/jpeg")


def test_validate_webp_happy():
    assert validate_image_bytes(_WEBP, "image/webp") == (True, "image/webp")


def test_validate_gif87a_happy():
    assert validate_image_bytes(_GIF87, "image/gif") == (True, "image/gif")


def test_validate_gif89a_happy():
    assert validate_image_bytes(_GIF89, "image/gif") == (True, "image/gif")


def test_validate_header_mismatch_rejected():
    ok, reason = validate_image_bytes(_PNG, "image/jpeg")
    assert ok is False
    assert reason == "header_mismatch"


def test_validate_blob_too_short_rejected():
    ok, reason = validate_image_bytes(b"\x89", "image/png")
    assert ok is False
    assert reason == "blob_too_short"


def test_validate_unknown_declared_mime_rejected():
    ok, reason = validate_image_bytes(_PNG, "image/svg+xml")
    assert ok is False
    assert reason == "unknown_declared_mime"


def test_validate_webp_partial_riff_rejected():
    """RIFF header but missing WEBP marker at offset 8 — fails."""
    bad = b"RIFF" + b"\x00\x00\x00\x00" + b"AVI " + b"x" * 16
    ok, reason = validate_image_bytes(bad, "image/webp")
    assert ok is False
    assert reason == "header_mismatch"
