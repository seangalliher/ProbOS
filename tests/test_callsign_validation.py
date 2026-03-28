"""AD-485: Callsign validation tests."""
import re
import pytest


def _is_valid_callsign(name: str) -> bool:
    """Mirror of the validation function in runtime.py._run_naming_ceremony."""
    if not re.match(r"^[A-Za-z][A-Za-z' -]{0,18}[A-Za-z]$", name):
        return False
    _blocked = {
        "captain", "admiral", "ensign", "lieutenant", "commander",
        "senior", "sir", "madam", "doctor", "dr", "agent", "bot",
        "ai", "system", "probos", "computer", "ship", "null", "none",
        "undefined", "test", "admin", "root", "god", "lord",
        "bridge", "engineering", "sickbay", "ops", "helm", "conn",
        "scout", "builder", "architect", "counselor", "surgeon",
        "pharmacist", "pathologist", "diagnostician", "security",
        "operations", "tactical", "science", "medical", "comms",
        "transporter", "holodeck", "brig", "armory", "shuttle",
        "turbolift", "quarters", "wardroom", "ready room",
    }
    if name.lower().strip() in _blocked:
        return False
    if not any(c.isalpha() for c in name):
        return False
    return True


class TestCallsignValidation:
    """Tests for the callsign safety validation function."""

    def test_valid_human_name_accepted(self):
        """Valid human names should pass validation."""
        assert _is_valid_callsign("Riker")
        assert _is_valid_callsign("Chapel")
        assert _is_valid_callsign("Torres")
        assert _is_valid_callsign("Bashir")
        assert _is_valid_callsign("Sato")
        assert _is_valid_callsign("Reed")

    def test_too_long_rejected(self):
        """Names over 20 chars should be rejected by the regex."""
        assert not _is_valid_callsign("A" * 25)

    def test_empty_rejected(self):
        """Empty string should be rejected."""
        assert not _is_valid_callsign("")

    def test_blocked_titles_rejected(self):
        """Rank titles and forbidden words should be rejected."""
        assert not _is_valid_callsign("Captain")
        assert not _is_valid_callsign("Admiral")
        assert not _is_valid_callsign("Doctor")

    def test_numbers_rejected(self):
        """Names with numbers should fail the regex."""
        assert not _is_valid_callsign("Agent007")
        assert not _is_valid_callsign("R2D2")

    def test_special_chars_rejected(self):
        """Names with special characters/emoji should fail the regex."""
        assert not _is_valid_callsign("l33t")
        # Single char fails the 2-char minimum
        assert not _is_valid_callsign("X")

    def test_compound_names_accepted(self):
        """Compound names with hyphens, apostrophes, spaces should pass."""
        assert _is_valid_callsign("O'Brien")
        assert _is_valid_callsign("La Forge")

    def test_duplicate_callsign_rejected(self):
        """Duplicate check is in runtime, not the validation function.
        This test verifies the validation function doesn't reject unique valid names."""
        assert _is_valid_callsign("Wesley")
        assert _is_valid_callsign("Troi")

    def test_role_names_rejected(self):
        """Role names (agent types) should be rejected."""
        assert not _is_valid_callsign("Scout")
        assert not _is_valid_callsign("Builder")
        assert not _is_valid_callsign("Architect")
        assert not _is_valid_callsign("Counselor")

    def test_ship_locations_rejected(self):
        """Ship locations should be rejected."""
        assert not _is_valid_callsign("Bridge")
        assert not _is_valid_callsign("Sickbay")
        assert not _is_valid_callsign("Engineering")
        assert not _is_valid_callsign("Holodeck")
