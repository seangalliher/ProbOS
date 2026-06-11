"""BF-619 (Natural Conversation epic #882): end-of-turn hand-off detection.

The Captain's live group-chat test: Ezri ended her turn with "... Yeo, anything
on your end that I should fold into this picture?" and Yeo never answered — the
cascade did not pull him in. Root cause: AD-951's ``extract_directed_callsign``
matches a LEADING address only, but a natural hand-off comes at the END of a
turn. ``extract_handoff_callsign`` (BF-619) also detects a final-sentence
vocative and a trailing comma-vocative, while keeping the BF #467 discipline
(a message ABOUT a peer is not a hand-off).
"""
from __future__ import annotations

from probos.crew_profile import extract_directed_callsign, extract_handoff_callsign


# ===================== leading address (parity with AD-951) =====================


def test_leading_vocative_still_detected():
    assert extract_handoff_callsign("Yeo, what's your read?") == "yeo"
    assert extract_handoff_callsign("@yeo status?") == "yeo"
    assert extract_handoff_callsign("Yeo: go ahead") == "yeo"


def test_leading_parity_with_directed_callsign():
    # Anything the strict AD-951 matcher catches, the handoff matcher catches.
    for t in ("Yeo, hi", "@yeo hi", "Bones: report"):
        assert extract_handoff_callsign(t) == extract_directed_callsign(t)


# ===================== the BF-619 case: end-of-turn hand-off =====================


def test_final_sentence_leading_vocative():
    # The exact Captain-reported shape: a multi-sentence turn that hands off in
    # its LAST sentence. AD-951 missed this; BF-619 catches it.
    text = (
        "Looking at you now, still the black shirt. A digest sounds good. "
        "Yeo, anything on your end that I should fold into this picture?"
    )
    assert extract_directed_callsign(text) is None   # the old behavior (missed)
    assert extract_handoff_callsign(text) == "yeo"   # the fix


def test_trailing_comma_vocative():
    assert extract_handoff_callsign("So what do you think, Yeo?") == "yeo"
    assert extract_handoff_callsign("I'll defer to you on this one, Bones.") == "bones"


def test_trailing_at_vocative():
    assert extract_handoff_callsign("Your call on the away team, @reed") == "reed"


# ===================== discipline: ABOUT a peer is NOT a hand-off =====================


def test_referential_mention_is_not_a_handoff():
    # No comma/colon before the trailing name -> referential, not a hand-off.
    assert extract_handoff_callsign("I agree with Yeo.") is None
    assert extract_handoff_callsign("I already briefed Yeo on this.") is None
    assert extract_handoff_callsign("The plan Yeo proposed looks sound.") is None


def test_midsentence_mention_is_not_a_handoff():
    # A peer named mid-clause without a directed comma is not an address.
    assert extract_handoff_callsign("Yeo and I reviewed the logs together.") is None


def test_empty_and_none_safe():
    assert extract_handoff_callsign("") is None
    assert extract_handoff_callsign("   ") is None
    assert extract_handoff_callsign("Just a statement with no address.") is None


def test_returns_lowercase():
    assert extract_handoff_callsign("EZRI, your read?") == "ezri"
    assert extract_handoff_callsign("anything to add, EZRI?") == "ezri"
