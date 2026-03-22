"""Tests for AD-393: Personality Activation — Big Five traits wired into system prompt."""

from __future__ import annotations

from unittest.mock import patch

from probos.cognitive.standing_orders import (
    _build_personality_block,
    clear_cache,
    compose_instructions,
)


def _make_profile(
    *,
    display_name: str = "TestAgent",
    callsign: str = "",
    department: str = "science",
    role: str = "crew",
    openness: float = 0.5,
    conscientiousness: float = 0.5,
    extraversion: float = 0.5,
    agreeableness: float = 0.5,
    neuroticism: float = 0.5,
) -> dict:
    return {
        "display_name": display_name,
        "callsign": callsign,
        "department": department,
        "role": role,
        "personality": {
            "openness": openness,
            "conscientiousness": conscientiousness,
            "extraversion": extraversion,
            "agreeableness": agreeableness,
            "neuroticism": neuroticism,
        },
    }


class TestBuildPersonalityBlock:
    """Tests for _build_personality_block()."""

    def setup_method(self):
        clear_cache()

    def test_high_trait_guidance(self):
        """High openness (>=0.7) produces the 'high' guidance text."""
        profile = _make_profile(openness=0.9)
        with patch("probos.cognitive.standing_orders.load_seed_profile", return_value=profile):
            block = _build_personality_block("test_agent", "science")
        assert "Explore creative and unconventional approaches" in block

    def test_low_trait_guidance(self):
        """Low neuroticism (<=0.3) produces the 'low' guidance text."""
        profile = _make_profile(neuroticism=0.2)
        with patch("probos.cognitive.standing_orders.load_seed_profile", return_value=profile):
            block = _build_personality_block("test_agent_low", "science")
        assert "Stay calm under pressure" in block

    def test_neutral_trait_no_guidance(self):
        """Neutral agreeableness (0.5) produces no guidance for that trait."""
        profile = _make_profile(agreeableness=0.5)
        with patch("probos.cognitive.standing_orders.load_seed_profile", return_value=profile):
            block = _build_personality_block("test_agent_neutral", "science")
        assert "consensus" not in block.lower()
        assert "devil's advocate" not in block.lower()

    def test_identity_line_with_callsign(self):
        """Profile with callsign produces 'You are {callsign}, the {display_name}' format."""
        profile = _make_profile(callsign="Scotty", display_name="Builder", role="chief", department="engineering")
        with patch("probos.cognitive.standing_orders.load_seed_profile", return_value=profile):
            block = _build_personality_block("test_agent_cs", "engineering")
        assert "You are Scotty, the Builder" in block
        assert "department chief of Engineering department" in block

    def test_identity_line_without_callsign(self):
        """Profile without callsign uses display_name only."""
        profile = _make_profile(callsign="", display_name="Builder", role="officer")
        with patch("probos.cognitive.standing_orders.load_seed_profile", return_value=profile):
            block = _build_personality_block("test_agent_nocs", "engineering")
        assert "You are the Builder" in block
        assert "Scotty" not in block

    def test_no_profile_returns_empty(self):
        """Agent type with no YAML returns empty string."""
        with patch("probos.cognitive.standing_orders.load_seed_profile", return_value={}):
            block = _build_personality_block("nonexistent_agent_type")
        assert block == ""

    def test_personality_in_composed_instructions(self):
        """Personality block appears between hardcoded instructions and Federation Constitution."""
        # Use a real architect profile (lives in crew_profiles/architect.yaml)
        clear_cache()
        result = compose_instructions("architect", "I am the Architect.")
        # Check ordering: hardcoded → personality → federation
        hardcoded_pos = result.find("I am the Architect.")
        personality_pos = result.find("## Crew Identity & Personality")
        fed_pos = result.find("## Federation Constitution")
        assert hardcoded_pos < personality_pos < fed_pos, (
            f"Expected hardcoded ({hardcoded_pos}) < personality ({personality_pos}) "
            f"< federation ({fed_pos})"
        )

    def test_all_traits_high(self):
        """All traits at 0.9 produces all 5 guidance lines."""
        profile = _make_profile(
            openness=0.9,
            conscientiousness=0.9,
            extraversion=0.9,
            agreeableness=0.9,
            neuroticism=0.9,
        )
        with patch("probos.cognitive.standing_orders.load_seed_profile", return_value=profile):
            block = _build_personality_block("test_agent_all_high", "science")
        assert "Explore creative" in block
        assert "Be thorough" in block
        assert "Be proactive" in block
        assert "Seek consensus" in block
        assert "Flag risks early" in block

    def test_all_traits_neutral(self):
        """All traits at 0.5 produces identity line only (no behavioral style section)."""
        profile = _make_profile(
            openness=0.5,
            conscientiousness=0.5,
            extraversion=0.5,
            agreeableness=0.5,
            neuroticism=0.5,
        )
        with patch("probos.cognitive.standing_orders.load_seed_profile", return_value=profile):
            block = _build_personality_block("test_agent_all_neutral", "science")
        assert "## Crew Identity & Personality" in block
        assert "You are the TestAgent" in block
        assert "Behavioral Style:" not in block

    def test_cache_is_used(self):
        """Call _build_personality_block() twice — load_seed_profile called only once (cached)."""
        clear_cache()
        profile = _make_profile(callsign="Cache", display_name="CacheTest")
        with patch("probos.cognitive.standing_orders.load_seed_profile", return_value=profile) as mock_load:
            _build_personality_block("test_agent_cache", "science")
            _build_personality_block("test_agent_cache", "science")
        assert mock_load.call_count == 1
