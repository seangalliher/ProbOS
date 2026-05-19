"""AD-721b-3 — Whisper model path resolver tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from probos.config import SystemConfig
from probos.settings.section_registry import get_section
from probos.voice.whisper_model import resolve_whisper_model_path


def test_resolver_default_path_relative_to_data_dir(tmp_path: Path) -> None:
    config = SystemConfig()
    # No file present yet — the resolver returns None but the EXPECTED
    # candidate is still data_dir / whisper / ggml-tiny.en.bin.
    assert resolve_whisper_model_path(config, tmp_path) is None
    target = tmp_path / "whisper" / "ggml-tiny.en.bin"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"ggml-fake-tiny.en bytes")
    resolved = resolve_whisper_model_path(config, tmp_path)
    assert resolved == target


def test_resolver_returns_none_when_file_absent(tmp_path: Path) -> None:
    config = SystemConfig()
    assert resolve_whisper_model_path(config, tmp_path) is None


def test_resolver_returns_path_when_file_present(tmp_path: Path) -> None:
    config = SystemConfig()
    target = tmp_path / "whisper" / "ggml-tiny.en.bin"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"ggml-fake-tiny.en bytes")
    resolved = resolve_whisper_model_path(config, tmp_path)
    assert resolved is not None
    assert resolved.exists()


def test_resolver_absolute_path_passes_through(tmp_path: Path) -> None:
    config = SystemConfig()
    custom = tmp_path / "custom" / "model.bin"
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_bytes(b"x")
    config.cognitive.whisper_model_path = str(custom)
    resolved = resolve_whisper_model_path(config, tmp_path)
    assert resolved == custom


def test_config_field_default_value() -> None:
    config = SystemConfig()
    assert config.cognitive.whisper_model_path == "whisper/ggml-tiny.en.bin"


def test_field_descriptor_registered_in_section_registry() -> None:
    section = get_section("llm_tiers")
    assert section is not None
    matches = [
        field
        for field in section.fields
        if field.field_id == "cognitive.whisper_model_path"
    ]
    assert len(matches) == 1, "whisper_model_path descriptor must be registered"
    field = matches[0]
    # FieldDescriptor uses hot_reload; whisper_model_path is restart-
    # required (loader caches path at boot) → hot_reload is False.
    assert field.hot_reload is False
    assert field.kind == "text"
