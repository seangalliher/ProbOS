"""AD-720e: audio attachment magic-byte validation + allow-list defaults."""
from __future__ import annotations

from probos.attachments.mime import validate_image_bytes
from probos.config import AttachmentsConfig


def test_audio_mpeg_id3_signature_validates() -> None:
    blob = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 16
    ok, sniffed = validate_image_bytes(blob, "audio/mpeg")
    assert ok is True
    assert sniffed == "audio/mpeg"


def test_audio_mpeg_frame_sync_validates() -> None:
    blob = b"\xff\xfb\x00\x00" + b"\x00" * 32
    ok, sniffed = validate_image_bytes(blob, "audio/mpeg")
    assert ok is True
    assert sniffed == "audio/mpeg"


def test_audio_mp4_ftyp_signature_validates() -> None:
    blob = b"\x00\x00\x00\x20" + b"ftypM4A " + b"\x00" * 32
    ok, sniffed = validate_image_bytes(blob, "audio/mp4")
    assert ok is True
    assert sniffed == "audio/mp4"


def test_audio_ogg_signature_validates() -> None:
    blob = b"OggS\x00\x02" + b"\x00" * 32
    ok, sniffed = validate_image_bytes(blob, "audio/ogg")
    assert ok is True
    assert sniffed == "audio/ogg"


def test_audio_attachments_in_default_allowed_mimes() -> None:
    allowed = set(AttachmentsConfig().allowed_mime_types)
    for mime in ("audio/webm", "audio/wav", "audio/mpeg", "audio/mp4", "audio/ogg"):
        assert mime in allowed, f"{mime} missing from default allow-list"
