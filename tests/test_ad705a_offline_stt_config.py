"""AD-705a — Offline STT config + license-file regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from probos.config import SystemConfig
from probos.settings.section_registry import get_section

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_offline_stt_enabled_default_false() -> None:
    config = SystemConfig()
    assert config.cognitive.offline_stt_enabled is False


def test_offline_stt_enabled_field_validates_bool() -> None:
    # Construction-time validation: a non-coercible value must be rejected
    # by the Pydantic model (Pydantic v2 does coerce "true"/"false" by
    # default, but a dict has no bool coercion path).
    from probos.config import CognitiveConfig

    with pytest.raises(ValidationError):
        CognitiveConfig(offline_stt_enabled={"not": "a bool"})  # type: ignore[arg-type]


def test_field_descriptor_registered() -> None:
    section = get_section("llm_tiers")
    assert section is not None
    matches = [
        field
        for field in section.fields
        if field.field_id == "cognitive.offline_stt_enabled"
    ]
    assert len(matches) == 1
    field = matches[0]
    # hot_reload=True (i.e. NOT restart-required) per AD-705a — the
    # subscription is keyed off the live snapshot.
    assert field.hot_reload is True
    assert field.kind == "bool"


def test_license_file_carries_whisper_cpp_entry() -> None:
    text = (REPO_ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    assert "whisper.cpp" in text
    # The whisper.cpp section must mention MIT in the same vicinity (within
    # ~500 chars — the section's body).
    idx = text.find("whisper.cpp")
    assert idx != -1
    window = text[idx : idx + 500]
    assert "MIT" in window


def test_license_file_carries_whisper_model_entry() -> None:
    text = (REPO_ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    # The OpenAI Whisper model-weights section header lives separately.
    assert "OpenAI Whisper" in text
    idx = text.find("OpenAI Whisper")
    assert idx != -1
    window = text[idx : idx + 500]
    assert "MIT" in window
    assert "tiny.en" in window or "ggml" in window
