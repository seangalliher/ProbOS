"""AD-718e (Wave 166) - Multi-language voice selection tests."""

from __future__ import annotations

import pytest

from probos.crew_profile import CrewProfile, VoiceProfile


def test_voice_profile_default_language_is_en() -> None:
    vp = VoiceProfile()
    assert vp.language == "en"


def test_voice_profile_language_normalized_empty_to_en() -> None:
    vp = VoiceProfile(language="")
    assert vp.language == "en"


def test_voice_profile_language_strips_whitespace() -> None:
    vp = VoiceProfile(language="  es  ")
    assert vp.language == "es"


def test_voice_profile_language_rejects_invalid_chars() -> None:
    with pytest.raises(ValueError, match="language"):
        VoiceProfile(language="en/US")
    with pytest.raises(ValueError, match="language"):
        VoiceProfile(language="EN")  # uppercase prefix rejected


def test_voice_profile_language_accepts_es_fr_de() -> None:
    for code in ("es", "fr", "de", "it", "nl", "pt", "en-US", "es_ES", "pt_BR"):
        vp = VoiceProfile(language=code)
        assert vp.language == code


def test_voice_profile_to_dict_includes_language() -> None:
    d = VoiceProfile(language="es").to_dict()
    assert d.get("language") == "es"


def test_voice_profile_from_dict_missing_language_defaults_to_en() -> None:
    """Backward-compat: existing rows without 'language' deserialize to 'en'."""
    legacy_dict = {
        "voice_name": "",
        "pitch": 0.9,
        "rate": 0.95,
        "volume": 0.8,
        "wake_phrase": "",
    }
    vp = VoiceProfile.from_dict(legacy_dict)
    assert vp.language == "en"


def test_voice_profile_language_persists_through_crew_profile_roundtrip() -> None:
    crew = CrewProfile(agent_id="a1", agent_type="counselor")
    crew.voice = VoiceProfile(voice_name="", language="fr")
    payload = crew.to_dict()
    restored = CrewProfile.from_dict(payload)
    assert restored.voice.language == "fr"
