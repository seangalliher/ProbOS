"""BF-147: Temporal reasoning probe — watch section vocabulary + temporal match weight."""

import math
import pytest
from unittest.mock import MagicMock, AsyncMock

from probos.cognitive.memory_probes import (
    _TEMPORAL_EPISODES,
    _PROBE_STOP_WORDS,
    TemporalReasoningProbe,
    _make_test_episode,
    _ward_room_content,
)
from probos.cognitive.source_governance import parse_anchor_query, _WATCH_SECTIONS


class TestBF147WatchSectionVocabulary:
    """Probe data uses valid derive_watch_section() values."""

    def test_temporal_episodes_use_canonical_watch_values(self):
        """BF-147: _TEMPORAL_EPISODES must use canonical watch section names."""
        from probos.cognitive.orientation import derive_watch_section
        # Get all valid watch section names by checking all 24 hours
        valid_sections = {derive_watch_section(h) for h in range(24)}
        for ep in _TEMPORAL_EPISODES:
            assert ep["watch"] in valid_sections, (
                f"Episode watch='{ep['watch']}' is not a valid derive_watch_section() value. "
                f"Valid values: {valid_sections}"
            )

    def test_first_watch_episodes_use_first(self):
        """BF-147: First watch episodes use 'first', not 'first_watch'."""
        first_eps = [e for e in _TEMPORAL_EPISODES if "first watch" in e["content"].lower()]
        assert len(first_eps) >= 2
        for ep in first_eps:
            assert ep["watch"] == "first"

    def test_second_group_episodes_use_second_dog(self):
        """BF-147: Second group episodes use 'second_dog', not 'second_watch'."""
        second_eps = [e for e in _TEMPORAL_EPISODES if "second dog" in e["content"].lower()]
        assert len(second_eps) >= 2
        for ep in second_eps:
            assert ep["watch"] == "second_dog"

    def test_probe_stop_words_include_dog(self):
        """BF-147: 'dog' added to probe stop words for second dog watch."""
        assert "dog" in _PROBE_STOP_WORDS


class TestBF147RecentlyParsing:
    """parse_anchor_query handles 'recently' and 'most recently'."""

    def test_recently_matches(self):
        """BF-147: 'recently' should match the recent pattern."""
        result = parse_anchor_query("What was discussed recently?")
        assert result.time_range is not None

    def test_most_recently_matches(self):
        """BF-147: 'most recently' should match the recent pattern."""
        result = parse_anchor_query("What was discussed most recently?")
        assert result.time_range is not None

    def test_recent_still_matches(self):
        """BF-147: 'recent' should still match (regression check)."""
        result = parse_anchor_query("Any recent observations?")
        assert result.time_range is not None


class TestBF147TemporalMatchWeight:
    """Temporal match bonus in score_recall()."""

    def test_temporal_match_adds_bonus(self):
        """BF-147: temporal_match=True adds temporal_match_weight to composite."""
        from probos.cognitive.episodic import EpisodicMemory
        from probos.types import Episode, AnchorFrame

        ep = Episode(
            id="test",
            user_input="test",
            agent_ids=["a1"],
            timestamp=0,
            anchors=AnchorFrame(watch_section="first"),
        )

        without = EpisodicMemory.score_recall(ep, 0.5, temporal_match=False)
        with_match = EpisodicMemory.score_recall(ep, 0.5, temporal_match=True)
        assert with_match.composite_score > without.composite_score
        assert abs(with_match.composite_score - without.composite_score - 0.10) < 0.001

    def test_temporal_match_default_false(self):
        """BF-147: temporal_match defaults to False — no behavioral change for existing callers."""
        from probos.cognitive.episodic import EpisodicMemory
        from probos.types import Episode

        ep = Episode(id="test", user_input="test", agent_ids=["a1"], timestamp=0)
        baseline = EpisodicMemory.score_recall(ep, 0.5)
        explicit_false = EpisodicMemory.score_recall(ep, 0.5, temporal_match=False)
        assert baseline.composite_score == explicit_false.composite_score

    def test_custom_temporal_match_weight(self):
        """BF-147: temporal_match_weight is configurable."""
        from probos.cognitive.episodic import EpisodicMemory
        from probos.types import Episode, AnchorFrame

        ep = Episode(
            id="test", user_input="test", agent_ids=["a1"], timestamp=0,
            anchors=AnchorFrame(watch_section="first"),
        )
        result = EpisodicMemory.score_recall(ep, 0.5, temporal_match=True, temporal_match_weight=0.20)
        without = EpisodicMemory.score_recall(ep, 0.5, temporal_match=False)
        assert abs(result.composite_score - without.composite_score - 0.20) < 0.001

    def test_negative_temporal_weight_clamped(self):
        """BF-147: negative temporal_match_weight clamped to 0.0."""
        from probos.cognitive.episodic import EpisodicMemory
        from probos.types import Episode, AnchorFrame

        ep = Episode(
            id="test", user_input="test", agent_ids=["a1"], timestamp=0,
            anchors=AnchorFrame(watch_section="first"),
        )
        result = EpisodicMemory.score_recall(ep, 0.5, temporal_match=True, temporal_match_weight=-0.5)
        without = EpisodicMemory.score_recall(ep, 0.5, temporal_match=False)
        assert result.composite_score == without.composite_score
