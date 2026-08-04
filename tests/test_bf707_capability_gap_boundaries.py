"""BF-707: ``_CAPABILITY_GAP_RE`` matched inside ordinary words.

The regex had no word boundaries, so two branches fired on substrings of
perfectly normal English. That is not cosmetic: ``is_capability_gap`` drives the
self-modification pipeline, so a false positive makes the runtime conclude it is
missing a capability because an agent used a common word.

    lack(?:s|ing)?   ->  b|lack|, S|lack|, b|lack|board, p|lack|et
    can['\u2019]?t   ->  signifi|cant|, va|cant|, s|cant|, appli|cant|

The second branch is the severe one and is NOT in the original report. The
apostrophe is optional, so the branch also matches the bare letters ``cant`` --
which sit inside **significant**, a word that appears constantly in agent prose.

These tests pin BOTH directions. Tightening a detector is only correct if it
still detects; a regex that matches nothing would satisfy the false-positive
half of this file and be far worse than the bug.
"""

import pytest

from probos.cognitive.decomposer import is_capability_gap


class TestOrdinaryWordsAreNotCapabilityGaps:
    """The regression. Every one of these returned True before BF-707."""

    @pytest.mark.parametrize(
        "sentence",
        [
            # `lack` inside a word -- the reported cases.
            "I formatted the file with black.",
            "Posting the summary to Slack now.",
            "The chart uses a black background.",
            "Blackboard rendering complete.",
            # `cant` inside a word -- found while fixing the above, and by far
            # the more common failure in real agent prose.
            "This is a significant improvement.",
            "The vacant slot was filled.",
            "A scant amount of data remains.",
            "I will decant the results into a table.",
            "The applicant list is ready for review.",
        ],
    )
    def test_ordinary_prose_does_not_register_a_gap(self, sentence):
        assert is_capability_gap(sentence) is False, (
            f"{sentence!r} was classified as a capability gap, which would "
            "drive the self-modification pipeline"
        )

    def test_significant_is_the_headline_case(self):
        """Called out on its own because of how ordinary the word is.

        An agent reporting a good result is the LAST thing that should be read
        as a capability gap.
        """
        assert is_capability_gap("That is a significant improvement.") is False


class TestRealCapabilityGapsStillRegister:
    """The other half. A detector that stopped detecting would be worse."""

    @pytest.mark.parametrize(
        "sentence",
        [
            "I can't do that.",
            "I can\u2019t do that.",  # curly apostrophe
            "I cant do that.",  # deliberate spelling tolerance, kept
            "I cannot access the network.",
            "I don't have a tool for that.",
            "I am unable to reach the host.",
            "There is no built-in capability for this.",
            "There is no native support for that format.",
            "That is not supported.",
            "That is not available.",
            "I lack the ability to browse.",
            "It lacks support for PDFs.",
            "I am lacking a renderer.",
            "It doesn't support that format.",
            "That is beyond my capabilities.",
            "That is outside the scope.",
        ],
    )
    def test_a_stated_limitation_still_registers(self, sentence):
        assert is_capability_gap(sentence) is True, (
            f"{sentence!r} is a real capability gap and must still trigger "
            "self-modification"
        )


class TestBoundaryPlacement:
    """Pins the property the single wrapper depends on.

    The fix wraps the whole alternation in ``\\b(?:...)\\b`` rather than putting
    a boundary on each branch. That is only sound while every alternative begins
    and ends with a word character -- a future branch starting or ending in
    punctuation would silently never match. This test makes that failure loud
    instead of invisible.
    """

    def test_a_gap_phrase_is_found_mid_sentence(self):
        """Boundaries must not restrict matching to the start of the string."""
        assert is_capability_gap("Sorry, but I cannot do that right now.") is True

    def test_a_gap_phrase_is_found_after_punctuation(self):
        assert is_capability_gap("Result: not supported.") is True

    def test_a_gap_phrase_is_found_when_it_ends_the_string(self):
        assert is_capability_gap("The feature is not available") is True

    def test_hyphenation_does_not_defeat_the_match(self):
        """A hyphen is a non-word char, so the leading boundary still holds."""
        assert is_capability_gap("well-known limitation: cannot render") is True
