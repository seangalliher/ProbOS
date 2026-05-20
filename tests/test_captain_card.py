import pytest
from probos.captain_card.card import CaptainCard, save_card, load_card
import tempfile
from pathlib import Path

def test_captain_card_creation_and_persistence():
    card = CaptainCard(name="Jean-Luc Picard", email="picard@starfleet.com", preferred_work_hours="09:00-17:00", timezone="Alpha Quadrant", voice_profile="Ezri", avatar_theme="sovereign")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "captain_card.json"
        assert save_card(card, path)
        loaded = load_card(path)
        assert loaded.name == card.name
        assert loaded.email == card.email
        assert loaded.voice_profile == card.voice_profile
        assert loaded.avatar_theme == card.avatar_theme

def test_captain_card_system_context():
    card = CaptainCard(name="Benjamin Sisko", preferred_work_hours="10:00-18:00", timezone="Bajor", voice_profile="Computer", avatar_theme="defiant")
    ctx = card.to_system_context()
    assert "You are Yeo, Benjamin Sisko's personal assistant." in ctx
    assert "Working hours: 10:00-18:00 Bajor" in ctx
    assert "Voice: Computer" in ctx
    assert "Avatar: defiant" in ctx
