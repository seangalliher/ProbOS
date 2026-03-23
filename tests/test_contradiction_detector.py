"""Tests for memory contradiction detection (AD-403)."""

import time

import pytest

from probos.cognitive.contradiction_detector import (
    Contradiction,
    _jaccard_similarity,
    detect_contradictions,
)
from probos.types import Episode


def _make_episode(
    user_input: str,
    intents: list[str],
    agent_ids: list[str],
    success: bool = True,
    timestamp: float | None = None,
) -> Episode:
    """Helper to create an episode with given intents and outcomes."""
    outcomes = [
        {"intent": intent, "success": success, "status": "completed" if success else "failed"}
        for intent in intents
    ]
    return Episode(
        timestamp=timestamp or time.time(),
        user_input=user_input,
        dag_summary={"node_count": len(intents), "intent_types": intents},
        outcomes=outcomes,
        agent_ids=agent_ids,
        duration_ms=100.0,
    )


# ---------------------------------------------------------------------------
# detect_contradictions tests
# ---------------------------------------------------------------------------


class TestDetectContradictions:

    def test_no_contradictions_identical_outcomes(self):
        """Two episodes with same input and same success outcome → no contradictions."""
        ep_a = _make_episode("read the file foo.txt", ["read_file"], ["agent_a"], success=True, timestamp=1.0)
        ep_b = _make_episode("read the file foo.txt", ["read_file"], ["agent_a"], success=True, timestamp=2.0)

        result = detect_contradictions([ep_a, ep_b])
        assert result == []

    def test_contradiction_detected_opposite_outcomes(self):
        """Two episodes with near-identical inputs, same intent+agent, opposite outcomes → 1 contradiction."""
        ep_old = _make_episode("read the file foo.txt", ["read_file"], ["agent_a"], success=True, timestamp=1.0)
        ep_new = _make_episode("read the file foo.txt", ["read_file"], ["agent_a"], success=False, timestamp=2.0)

        result = detect_contradictions([ep_old, ep_new])
        assert len(result) == 1

        c = result[0]
        assert c.older_episode_id == ep_old.id
        assert c.newer_episode_id == ep_new.id
        assert c.older_outcome == "success"
        assert c.newer_outcome == "failure"
        assert c.intent == "read_file"
        assert c.agent_id == "agent_a"
        assert c.similarity == 1.0

    def test_below_similarity_threshold_no_match(self):
        """Two episodes with different inputs but same intent → 0 contradictions."""
        ep_a = _make_episode("read the file foo.txt", ["read_file"], ["agent_a"], success=True, timestamp=1.0)
        ep_b = _make_episode("completely unrelated query about weather", ["read_file"], ["agent_a"], success=False, timestamp=2.0)

        result = detect_contradictions([ep_a, ep_b])
        assert result == []

    def test_multiple_contradictions(self):
        """Three episodes forming two contradiction pairs → both detected."""
        ep_1 = _make_episode("read the file foo.txt", ["read_file"], ["agent_a"], success=True, timestamp=1.0)
        ep_2 = _make_episode("read the file foo.txt", ["read_file"], ["agent_a"], success=False, timestamp=2.0)
        ep_3 = _make_episode("read the file foo.txt", ["read_file"], ["agent_a"], success=True, timestamp=3.0)

        result = detect_contradictions([ep_1, ep_2, ep_3])
        # ep_1 vs ep_2 (success vs failure) and ep_2 vs ep_3 (failure vs success)
        assert len(result) == 2

    def test_empty_episodes_list(self):
        """Empty list → empty list, no crash."""
        result = detect_contradictions([])
        assert result == []

    def test_single_episode(self):
        """One episode → no contradictions."""
        ep = _make_episode("read file", ["read_file"], ["agent_a"], success=True)
        result = detect_contradictions([ep])
        assert result == []

    def test_contradiction_id_format(self):
        """Contradiction.id follows expected format."""
        c = Contradiction(
            older_episode_id="abc",
            newer_episode_id="def",
            intent="read_file",
            agent_id="agent_a",
            older_outcome="success",
            newer_outcome="failure",
            similarity=0.9,
        )
        assert c.id == "contradiction:abc:def"

    def test_sorted_by_similarity_descending(self):
        """Contradictions are sorted by similarity descending."""
        # Create two pairs with different similarities
        ep_a = _make_episode("read the file foo.txt", ["read_file"], ["agent_a"], success=True, timestamp=1.0)
        ep_b = _make_episode("read the file foo.txt", ["read_file"], ["agent_a"], success=False, timestamp=2.0)
        # This pair has slightly different input (lower Jaccard)
        ep_c = _make_episode("read the file foo.txt now", ["write_file"], ["agent_b"], success=True, timestamp=3.0)
        ep_d = _make_episode("read the file foo.txt now", ["write_file"], ["agent_b"], success=False, timestamp=4.0)

        result = detect_contradictions([ep_a, ep_b, ep_c, ep_d])
        if len(result) >= 2:
            assert result[0].similarity >= result[1].similarity

    def test_custom_similarity_threshold(self):
        """Custom threshold changes sensitivity."""
        ep_a = _make_episode("read the file foo.txt bar", ["read_file"], ["agent_a"], success=True, timestamp=1.0)
        ep_b = _make_episode("read the file foo.txt baz", ["read_file"], ["agent_a"], success=False, timestamp=2.0)

        # With high threshold, might not match
        high = detect_contradictions([ep_a, ep_b], similarity_threshold=0.99)
        # With low threshold, should match
        low = detect_contradictions([ep_a, ep_b], similarity_threshold=0.5)

        assert len(low) >= len(high)


# ---------------------------------------------------------------------------
# _jaccard_similarity tests
# ---------------------------------------------------------------------------


class TestJaccardSimilarity:

    def test_identical_texts(self):
        """Identical texts → 1.0."""
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_disjoint_texts(self):
        """Completely disjoint texts → 0.0."""
        assert _jaccard_similarity("foo bar", "baz qux") == 0.0

    def test_partial_overlap(self):
        """Partial overlap → correct ratio."""
        # "hello" overlaps, "world" and "there" differ
        # intersection = {"hello"}, union = {"hello", "world", "there"}
        result = _jaccard_similarity("hello world", "hello there")
        assert result == pytest.approx(1 / 3)

    def test_empty_first_input(self):
        """Empty first input → 0.0."""
        assert _jaccard_similarity("", "hello world") == 0.0

    def test_empty_second_input(self):
        """Empty second input → 0.0."""
        assert _jaccard_similarity("hello world", "") == 0.0

    def test_both_empty(self):
        """Both empty → 0.0."""
        assert _jaccard_similarity("", "") == 0.0

    def test_case_insensitive(self):
        """Comparison is case-insensitive."""
        assert _jaccard_similarity("Hello World", "hello world") == 1.0

    def test_duplicate_words_ignored(self):
        """Duplicate words are collapsed (set-based)."""
        # "hello hello" → {"hello"}, "hello world" → {"hello", "world"}
        result = _jaccard_similarity("hello hello", "hello world")
        assert result == pytest.approx(1 / 2)
