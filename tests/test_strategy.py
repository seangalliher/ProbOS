"""Tests for StrategyRecommender — Phase 11 Part A."""

from __future__ import annotations

import pytest

from probos.cognitive.strategy import StrategyOption, StrategyProposal, StrategyRecommender
from probos.types import IntentDescriptor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_descriptors() -> list[IntentDescriptor]:
    """Sample descriptors simulating existing system capabilities."""
    return [
        IntentDescriptor(name="read_file", params={"path": "file path"}, description="Read file contents"),
        IntentDescriptor(name="write_file", params={"path": "file path", "content": "data"}, description="Write data to file"),
        IntentDescriptor(name="run_command", params={"command": "shell command"}, description="Execute shell command"),
        IntentDescriptor(name="http_fetch", params={"url": "target URL"}, description="Fetch URL content"),
        IntentDescriptor(name="translate_text", params={"text": "source text", "target_lang": "language"}, description="Translate text between languages"),
    ]


# ---------------------------------------------------------------------------
# StrategyRecommender tests
# ---------------------------------------------------------------------------


class TestStrategyRecommender:
    """Tests for StrategyRecommender.propose()."""

    def test_propose_always_returns_at_least_one_option(self):
        """new_agent fallback is always included."""
        recommender = StrategyRecommender(
            intent_descriptors=[],
            llm_equipped_types=set(),
        )
        proposal = recommender.propose("play_audio", "Play audio files", {})
        assert len(proposal.options) >= 1
        assert any(o.strategy == "new_agent" for o in proposal.options)

    def test_zero_overlap_new_agent_highest(self):
        """Intent with zero keyword overlap → new_agent has highest confidence."""
        recommender = StrategyRecommender(
            intent_descriptors=_make_descriptors(),
            llm_equipped_types={"skill_agent"},
        )
        proposal = recommender.propose("play_audio", "Play audio files", {})
        # new_agent should be the recommended (highest confidence) option
        rec = proposal.recommended
        assert rec is not None
        assert rec.strategy == "new_agent"

    def test_overlap_with_llm_equipped_add_skill_recommended(self):
        """Intent overlapping LLM-equipped agent → add_skill recommended."""
        recommender = StrategyRecommender(
            intent_descriptors=_make_descriptors(),
            llm_equipped_types={"skill_agent"},
        )
        # "translate_text" overlaps with the existing translate_text descriptor
        proposal = recommender.propose(
            "translate_text", "Translate text between languages", {"text": "hello", "target_lang": "fr"}
        )
        rec = proposal.recommended
        assert rec is not None
        assert rec.strategy == "add_skill"

    def test_add_skill_confidence_higher_than_new_agent_reversibility(self):
        """add_skill confidence higher than new_agent when both viable (reversibility)."""
        recommender = StrategyRecommender(
            intent_descriptors=_make_descriptors(),
            llm_equipped_types={"skill_agent"},
        )
        proposal = recommender.propose(
            "translate_text", "Translate text between languages", {}
        )
        add_skill = next((o for o in proposal.options if o.strategy == "add_skill"), None)
        new_agent = next((o for o in proposal.options if o.strategy == "new_agent"), None)
        assert add_skill is not None
        assert new_agent is not None
        assert add_skill.confidence > new_agent.confidence

    def test_options_sorted_by_confidence_descending(self):
        """Multiple options returned sorted by confidence."""
        recommender = StrategyRecommender(
            intent_descriptors=_make_descriptors(),
            llm_equipped_types={"skill_agent"},
        )
        proposal = recommender.propose(
            "translate_text", "Translate text between languages", {}
        )
        confidences = [o.confidence for o in proposal.options]
        assert confidences == sorted(confidences, reverse=True)

    def test_recommended_property_returns_marked_option(self):
        """recommended property returns is_recommended=True option."""
        recommender = StrategyRecommender(
            intent_descriptors=[],
            llm_equipped_types=set(),
        )
        proposal = recommender.propose("something", "Do something", {})
        rec = proposal.recommended
        assert rec is not None
        assert rec.is_recommended is True

    def test_recommended_property_none_when_no_options(self):
        """recommended property returns None when no options (edge case)."""
        proposal = StrategyProposal(intent_name="x", intent_description="x", options=[])
        assert proposal.recommended is None

    def test_keyword_overlap_tokenization(self):
        """keyword_overlap tokenization matches AD-55 pattern."""
        recommender = StrategyRecommender(
            intent_descriptors=[],
            llm_equipped_types=set(),
        )
        # Tokens < 3 chars should be filtered
        tokens = recommender._tokenize("a to read_file now")
        assert "a" not in tokens
        assert "to" not in tokens
        assert "read" in tokens
        assert "file" in tokens
        assert "now" in tokens

    def test_strategy_option_fields_roundtrip(self):
        """StrategyOption fields roundtrip correctly."""
        opt = StrategyOption(
            strategy="new_agent",
            label="Create new FooAgent",
            reason="Test reason",
            confidence=0.75,
            target_agent_type=None,
            is_recommended=True,
        )
        assert opt.strategy == "new_agent"
        assert opt.label == "Create new FooAgent"
        assert opt.reason == "Test reason"
        assert opt.confidence == 0.75
        assert opt.target_agent_type is None
        assert opt.is_recommended is True

    def test_strategy_proposal_with_empty_options(self):
        """StrategyProposal with empty options has None recommended."""
        proposal = StrategyProposal(
            intent_name="test", intent_description="test", options=[]
        )
        assert proposal.options == []
        assert proposal.recommended is None

    def test_llm_equipped_types_filters_add_skill(self):
        """Agent type not in llm_equipped_types excluded from add_skill."""
        recommender = StrategyRecommender(
            intent_descriptors=_make_descriptors(),
            llm_equipped_types=set(),  # No LLM-equipped types
        )
        proposal = recommender.propose(
            "translate_text", "Translate text between languages", {}
        )
        # Should NOT propose add_skill since no LLM-equipped types exist
        add_skill = [o for o in proposal.options if o.strategy == "add_skill"]
        assert len(add_skill) == 0

    def test_safety_budget_risk_confidence(self):
        """Strategy confidence reflects action risk (safety budget axiom).

        A strategy requiring fewer destructive actions (add_skill — reversible)
        should score higher than one requiring more (new_agent — creates pool).
        """
        recommender = StrategyRecommender(
            intent_descriptors=_make_descriptors(),
            llm_equipped_types={"skill_agent"},
        )
        # Intent that overlaps existing descriptors → both strategies viable
        proposal = recommender.propose(
            "fetch_url", "Fetch content from URL", {"url": "http://example.com"}
        )
        add_skill = next((o for o in proposal.options if o.strategy == "add_skill"), None)
        new_agent = next((o for o in proposal.options if o.strategy == "new_agent"), None)
        if add_skill and new_agent:
            # Reversible strategy should have higher confidence
            assert add_skill.confidence >= new_agent.confidence

    def test_semantic_similarity_higher_confidence_for_similar_intents(self):
        """Semantically similar intent produces higher add_skill confidence
        than a dissimilar one."""
        recommender = StrategyRecommender(
            intent_descriptors=_make_descriptors(),
            llm_equipped_types={"skill_agent"},
        )
        # "download_page" is semantically close to "http_fetch" / "Fetch URL content"
        proposal_similar = recommender.propose(
            "download_page", "Download a web page from a URL", {}
        )
        # "bake_cake" has nothing to do with existing descriptors
        proposal_dissimilar = recommender.propose(
            "bake_cake", "Bake a delicious chocolate cake", {}
        )

        similar_skill = next(
            (o for o in proposal_similar.options if o.strategy == "add_skill"), None
        )
        dissimilar_skill = next(
            (o for o in proposal_dissimilar.options if o.strategy == "add_skill"), None
        )

        if similar_skill and dissimilar_skill:
            assert similar_skill.confidence > dissimilar_skill.confidence
        elif similar_skill and not dissimilar_skill:
            # Dissimilar has no add_skill option — semantically nothing matched
            assert similar_skill.confidence > 0.0
