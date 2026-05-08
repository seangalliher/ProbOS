"""BF #467: tests for is_directed_mention + broadcast-vs-DM routing."""
from __future__ import annotations

from probos.crew_profile import extract_callsign_mention, is_directed_mention


def test_leading_at_callsign_is_directed() -> None:
    assert is_directed_mention("@Tucker can you help me with this") is True


def test_leading_whitespace_then_at_is_directed() -> None:
    assert is_directed_mention("   @Tucker hello") is True


def test_referential_mention_is_not_directed() -> None:
    assert is_directed_mention("Hello crew, please welcome @Tucker") is False


def test_mention_after_punctuation_is_not_directed() -> None:
    assert is_directed_mention("Captain says: @Tucker should help") is False


def test_no_mention_returns_false() -> None:
    assert is_directed_mention("Just a normal broadcast") is False


def test_empty_string_returns_false() -> None:
    assert is_directed_mention("") is False
    assert is_directed_mention("   ") is False


def test_extract_still_finds_referential_mention() -> None:
    """The extractor returns the mention regardless — only the routing
    decision is gated by is_directed_mention."""
    out = extract_callsign_mention("Welcome @Tucker to the crew")
    assert out is not None
    assert out[0] == "Tucker"


def test_directed_and_extracted_for_same_string() -> None:
    s = "@Tucker hello"
    assert is_directed_mention(s) is True
    out = extract_callsign_mention(s)
    assert out is not None
    assert out[0] == "Tucker"


def test_referential_extract_but_not_directed() -> None:
    s = "Hello @Tucker"
    assert is_directed_mention(s) is False
    out = extract_callsign_mention(s)
    assert out is not None  # extractor still finds it for context
    assert out[0] == "Tucker"
