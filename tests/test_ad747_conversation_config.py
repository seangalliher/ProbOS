"""AD-747 — Always-on conversation config + AD-741 registry tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from probos.config import CognitiveConfig, SystemConfig
from probos.settings.section_registry import SECTIONS, resolve_dot_path


def test_conversation_mode_defaults() -> None:
    cfg = CognitiveConfig()
    assert cfg.conversation_mode_enabled is False
    assert cfg.conversation_silence_timeout_ms == 30000
    assert cfg.conversation_barge_in_enabled is True


def test_silence_timeout_validators() -> None:
    """``ge=1000 le=300000`` enforced by Pydantic Field."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CognitiveConfig(conversation_silence_timeout_ms=500)
    with pytest.raises(ValidationError):
        CognitiveConfig(conversation_silence_timeout_ms=400000)
    # Boundary values OK.
    assert CognitiveConfig(conversation_silence_timeout_ms=1000)
    assert CognitiveConfig(conversation_silence_timeout_ms=300000)


def test_ad741_registry_includes_three_new_fields() -> None:
    """Three new FieldDescriptors must appear under the llm_tiers section
    (sibling slot to the existing AD-705a offline_stt_enabled field)."""
    section = next(s for s in SECTIONS if s.section_id == "llm_tiers")
    field_ids = {f.field_id for f in section.fields}
    assert "cognitive.conversation_mode_enabled" in field_ids
    assert "cognitive.conversation_silence_timeout_ms" in field_ids
    assert "cognitive.conversation_barge_in_enabled" in field_ids


def test_all_three_fields_hot_reload() -> None:
    """All three AD-747 settings must be hot-reload (no restart required)."""
    section = next(s for s in SECTIONS if s.section_id == "llm_tiers")
    targets = {
        "cognitive.conversation_mode_enabled",
        "cognitive.conversation_silence_timeout_ms",
        "cognitive.conversation_barge_in_enabled",
    }
    for f in section.fields:
        if f.field_id in targets:
            assert f.hot_reload is True, (
                f"AD-747: field {f.field_id} must be hot-reload"
            )


def test_dotpath_resolution_for_new_fields() -> None:
    """resolve_dot_path must walk to the three new fields without raising —
    proves they exist as Pydantic attrs (phantom-field guard)."""
    cfg = SystemConfig()
    assert resolve_dot_path(cfg, "cognitive.conversation_mode_enabled") is False
    assert resolve_dot_path(cfg, "cognitive.conversation_silence_timeout_ms") == 30000
    assert resolve_dot_path(cfg, "cognitive.conversation_barge_in_enabled") is True


def test_ad747_no_browser_audio_in_backend_modules() -> None:
    """AD-733c-7 privacy invariant: AD-747 is frontend-only. No backend
    module should reference the conversationController path. Source-scan
    enforces the invariant."""
    backend_dir = Path(__file__).resolve().parent.parent / "src" / "probos"
    forbidden = "conversationController"
    for path in backend_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert forbidden not in text, (
            f"AD-747: backend module {path.name} references browser-only "
            f"{forbidden!r}; conversation lifecycle must stay in the browser."
        )
