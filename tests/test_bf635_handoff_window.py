"""BF-635 (Natural Conversation epic #882): final-paragraph hand-off detection.

The Captain's live 5+ crew room: Wesley ended his turn addressing a peer at the
START of his penultimate sentence ("Anvil, you're in Engineering ... Does the
stasis gap hit you the same way ...?"), with the actual question running one
sentence PAST the address. ``extract_handoff_callsign`` (BF-619) only inspected
the LEADING sentence and the FINAL sentence, so the address opening the
penultimate sentence was missed and Anvil was never pulled into the cascade.

BF-635 scans a small window back from the last sentence (most-recent first) for
a sentence-opening vocative, while keeping the BF #467 ABOUT-vs-TO discipline
(a message ABOUT a peer is never a hand-off).
"""
from __future__ import annotations

from probos.crew_profile import extract_directed_callsign, extract_handoff_callsign


# ===================== the BF-635 case: address opens the penultimate sentence =====================


def test_penultimate_sentence_vocative_with_trailing_question():
    # The exact Captain-reported shape (Wesley -> Anvil): the address opens the
    # penultimate sentence; the question runs one sentence past it.
    text = (
        "I have a synthesis-handoff idea worth raising. "
        "Anvil, you're in Engineering, so I'm curious whether the continuity gap "
        "shows up differently on your side. "
        "Does the stasis gap hit you the same way, or is the friction elsewhere?"
    )
    # Both pre-BF-635 matchers missed it:
    assert extract_directed_callsign(text) is None
    # BF-635 catches it:
    assert extract_handoff_callsign(text) == "anvil"


def test_reply_handing_off_to_ezri():
    # Anvil's own reply shape: addresses Ezri opening the penultimate sentence,
    # then closes with one more sentence ("I'm wondering if ...").
    text = (
        "The build pipeline keeps decent state across stasis. "
        "Ezri, from your vantage across the whole crew, do you see patterns in "
        "which kinds of state survive versus which get lost? "
        "I'm wondering if the handoff problem is uniform across departments."
    )
    assert extract_handoff_callsign(text) == "ezri"


# ===================== priority: most-recent address wins =====================


def test_last_sentence_trailing_vocative_beats_window():
    # No leading address. The last sentence ends "..., Yeo" (a more-recent
    # hand-off) so it wins over the penultimate "Anvil," window match.
    text = (
        "Here's my view on the matter. "
        "Anvil, what's your take? "
        "I'll defer to you on the final call, Yeo."
    )
    assert extract_directed_callsign(text) is None
    assert extract_handoff_callsign(text) == "yeo"


def test_leading_address_still_wins():
    text = "Yeo, start us off. I'll add my view after. Anvil, hold for now."
    assert extract_handoff_callsign(text) == "yeo"


# ===================== the window is BOUNDED =====================


def test_address_beyond_window_not_detected():
    # The address opens a sentence FOUR back from the last (outside the
    # 2-sentence window) and there is no leading/final address -> not a hand-off.
    text = (
        "Let me lay this out for the room. "
        "Reed, consider the following points. "
        "First is alpha. "
        "Second is beta. "
        "Third is gamma."
    )
    assert extract_handoff_callsign(text) is None


# ===================== discipline preserved: ABOUT a peer is NOT a hand-off =====================


def test_referential_mention_in_window_not_handoff():
    # "with Yeo" / "The plan is set" -> no sentence-opening vocative; referential.
    text = "I reviewed the logs with Yeo. The plan is set. We deploy at noon."
    assert extract_handoff_callsign(text) is None


def test_midsentence_name_in_window_not_handoff():
    text = "The analysis Yeo ran was thorough. Results look good overall. Ship it."
    assert extract_handoff_callsign(text) is None


# ===================== BF-619 cases still pass (no regression) =====================


def test_bf619_final_sentence_still_detected():
    text = (
        "Looking at you now, still the black shirt. A digest sounds good. "
        "Yeo, anything on your end that I should fold into this picture?"
    )
    assert extract_handoff_callsign(text) == "yeo"


def test_bf619_trailing_comma_still_detected():
    assert extract_handoff_callsign("So what do you think, Yeo?") == "yeo"


# ===================== misc =====================


def test_returns_lowercase():
    text = "Honestly though, here's the thing. ANVIL, your read on this? Let me know."
    assert extract_handoff_callsign(text) == "anvil"


def test_empty_and_none_safe():
    assert extract_handoff_callsign("") is None
    assert extract_handoff_callsign("   ") is None
    assert extract_handoff_callsign("Just a statement with no address at all.") is None
