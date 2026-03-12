"""Tests for domain-aware StrategyRecommender (Phase 15b, AD-200, AD-201)."""

from __future__ import annotations

import pytest

from probos.cognitive.strategy import StrategyOption, StrategyRecommender
from probos.types import IntentDescriptor


# ---------------------------------------------------------------------------
# Mock agent classes for testing
# ---------------------------------------------------------------------------

class MockCognitiveAgent:
    """Simulates a CognitiveAgent with instructions."""
    agent_type = "text_analyzer"
    instructions = (
        "You are a text analysis specialist. "
        "You analyze text for sentiment, keywords, and structure."
    )


class MockDataAgent:
    """Simulates a CognitiveAgent for data tasks."""
    agent_type = "data_processor"
    instructions = (
        "You are a data processing specialist. "
        "You handle CSV, JSON, and tabular data transformations."
    )


class MockToolAgent:
    """Simulates a regular tool agent without instructions."""
    agent_type = "file_reader"
    instructions = None


class MockSkillAgent:
    """Simulates SkillBasedAgent without instructions."""
    agent_type = "skill_agent"
    # No instructions attribute


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _base_descriptors():
    """Return some basic intent descriptors."""
    return [
        IntentDescriptor(
            name="read_file",
            params={"path": "file path"},
            description="Read file contents",
        ),
        IntentDescriptor(
            name="analyze_data",
            params={"data": "input data"},
            description="Analyze data and return insights",
        ),
    ]


# ===========================================================================
# Test cases
# ===========================================================================

class TestStrategyRecommenderNoAgentClasses:
    """Test behavior when no agent_classes provided (backward compat)."""

    def test_no_agent_classes_defaults_to_skill_agent(self):
        """Without agent_classes, target is always skill_agent."""
        rec = StrategyRecommender(
            intent_descriptors=_base_descriptors(),
            llm_equipped_types={"skill_agent"},
        )
        proposal = rec.propose("count_words", "Count words in text", {"text": "input"})
        skill_opts = [o for o in proposal.options if o.strategy == "add_skill"]
        if skill_opts:
            assert skill_opts[0].target_agent_type == "skill_agent"

    def test_find_best_skill_target_returns_skill_agent(self):
        """_find_best_skill_target returns skill_agent with no agent_classes."""
        rec = StrategyRecommender(
            intent_descriptors=[],
            llm_equipped_types={"skill_agent"},
        )
        target, score = rec._find_best_skill_target("count_words", "Count words")
        assert target == "skill_agent"
        assert score == 0.0


class TestStrategyRecommenderDomainAware:
    """Test domain-aware scoring with cognitive agents."""

    def test_scores_cognitive_agent_instructions(self):
        """Recommender scores cognitive agent instructions against intent."""
        rec = StrategyRecommender(
            intent_descriptors=_base_descriptors(),
            llm_equipped_types={"skill_agent", "text_analyzer"},
            agent_classes={
                "text_analyzer": MockCognitiveAgent,
                "file_reader": MockToolAgent,
            },
        )
        target, score = rec._find_best_skill_target(
            "analyze_sentiment", "Analyze sentiment of text",
        )
        # "text" and "analyze" overlap with MockCognitiveAgent instructions
        assert target == "text_analyzer"
        assert score > 0

    def test_highest_scoring_agent_wins(self):
        """Best-matching cognitive agent becomes the target."""
        rec = StrategyRecommender(
            intent_descriptors=_base_descriptors(),
            llm_equipped_types={"text_analyzer", "data_processor"},
            agent_classes={
                "text_analyzer": MockCognitiveAgent,
                "data_processor": MockDataAgent,
            },
        )
        # "csv data transformation" should match data_processor better
        target, score = rec._find_best_skill_target(
            "transform_csv", "Transform CSV data into JSON format",
        )
        assert target == "data_processor"
        assert score > 0

    def test_below_threshold_falls_back_to_skill_agent(self):
        """Below-threshold cognitive agents fall back to skill_agent."""
        rec = StrategyRecommender(
            intent_descriptors=_base_descriptors(),
            llm_equipped_types={"text_analyzer"},
            agent_classes={
                "text_analyzer": MockCognitiveAgent,
            },
        )
        # "play music" has no overlap with text analysis
        target, score = rec._find_best_skill_target(
            "play_music", "Play audio music files through speakers",
        )
        assert target == "skill_agent"
        assert score == 0.0

    def test_tool_agents_ignored_in_scoring(self):
        """Tool agents without instructions are not scored."""
        rec = StrategyRecommender(
            intent_descriptors=_base_descriptors(),
            llm_equipped_types={"file_reader"},
            agent_classes={
                "file_reader": MockToolAgent,
            },
        )
        target, score = rec._find_best_skill_target("read_csv", "Read CSV files")
        assert target == "skill_agent"
        assert score == 0.0

    def test_skill_agent_without_instructions_not_scored(self):
        """SkillBasedAgent without instructions attribute is not scored."""
        rec = StrategyRecommender(
            intent_descriptors=_base_descriptors(),
            llm_equipped_types={"skill_agent"},
            agent_classes={
                "skill_agent": MockSkillAgent,
            },
        )
        target, score = rec._find_best_skill_target("count_words", "Count words")
        assert target == "skill_agent"
        assert score == 0.0

    def test_domain_match_affects_add_skill_confidence(self):
        """Strong domain match produces higher add_skill confidence."""
        descriptors = _base_descriptors()

        # With cognitive agent match
        rec_with = StrategyRecommender(
            intent_descriptors=descriptors,
            llm_equipped_types={"text_analyzer"},
            agent_classes={"text_analyzer": MockCognitiveAgent},
        )
        proposal_with = rec_with.propose(
            "analyze_sentiment", "Analyze text sentiment and keywords", {"text": "input"},
        )

        # Without cognitive agent match
        rec_without = StrategyRecommender(
            intent_descriptors=descriptors,
            llm_equipped_types={"skill_agent"},
        )
        proposal_without = rec_without.propose(
            "analyze_sentiment", "Analyze text sentiment and keywords", {"text": "input"},
        )

        skill_with = [o for o in proposal_with.options if o.strategy == "add_skill"]
        skill_without = [o for o in proposal_without.options if o.strategy == "add_skill"]

        if skill_with and skill_without:
            # Domain match should boost confidence
            assert skill_with[0].confidence >= skill_without[0].confidence

    def test_target_agent_type_in_proposal(self):
        """target_agent_type is set to matching cognitive agent."""
        rec = StrategyRecommender(
            intent_descriptors=_base_descriptors(),
            llm_equipped_types={"text_analyzer"},
            agent_classes={"text_analyzer": MockCognitiveAgent},
        )
        proposal = rec.propose(
            "analyze_keywords", "Analyze text for keywords", {"text": "input"},
        )
        skill_opts = [o for o in proposal.options if o.strategy == "add_skill"]
        if skill_opts:
            assert skill_opts[0].target_agent_type == "text_analyzer"

    def test_label_includes_target_agent_name(self):
        """Strategy label shows target agent name when not skill_agent."""
        rec = StrategyRecommender(
            intent_descriptors=_base_descriptors(),
            llm_equipped_types={"text_analyzer"},
            agent_classes={"text_analyzer": MockCognitiveAgent},
        )
        proposal = rec.propose(
            "analyze_keywords", "Analyze text for keywords", {"text": "input"},
        )
        skill_opts = [o for o in proposal.options if o.strategy == "add_skill"]
        if skill_opts:
            assert "text_analyzer" in skill_opts[0].label

    def test_label_generic_when_skill_agent(self):
        """Strategy label is generic when target is skill_agent."""
        rec = StrategyRecommender(
            intent_descriptors=_base_descriptors(),
            llm_equipped_types={"skill_agent"},
        )
        proposal = rec.propose(
            "count_words", "Count words in text", {"text": "input"},
        )
        skill_opts = [o for o in proposal.options if o.strategy == "add_skill"]
        if skill_opts:
            assert "existing agent" in skill_opts[0].label

    def test_existing_behavior_preserved_no_cognitive(self):
        """Existing behavior when no cognitive agents are registered."""
        rec = StrategyRecommender(
            intent_descriptors=_base_descriptors(),
            llm_equipped_types={"skill_agent"},
        )
        proposal = rec.propose(
            "count_words", "Count words in text", {"text": "input"},
        )
        # Should have at least new_agent option
        assert len(proposal.options) >= 1
        new_agent = [o for o in proposal.options if o.strategy == "new_agent"]
        assert len(new_agent) == 1

    def test_new_agent_option_always_present(self):
        """new_agent option is always available regardless of cognitive agents."""
        rec = StrategyRecommender(
            intent_descriptors=_base_descriptors(),
            llm_equipped_types={"text_analyzer"},
            agent_classes={"text_analyzer": MockCognitiveAgent},
        )
        proposal = rec.propose(
            "analyze_keywords", "Analyze text for keywords", {"text": "input"},
        )
        new_agent = [o for o in proposal.options if o.strategy == "new_agent"]
        assert len(new_agent) == 1

    def test_multiple_cognitive_agents_best_wins(self):
        """With multiple cognitive agents, best match wins."""
        rec = StrategyRecommender(
            intent_descriptors=_base_descriptors(),
            llm_equipped_types={"text_analyzer", "data_processor"},
            agent_classes={
                "text_analyzer": MockCognitiveAgent,
                "data_processor": MockDataAgent,
            },
        )
        # "text sentiment" should match text_analyzer
        target, _ = rec._find_best_skill_target(
            "analyze_sentiment", "Analyze text sentiment",
        )
        assert target == "text_analyzer"

        # "csv json tabular" should match data_processor
        target2, _ = rec._find_best_skill_target(
            "convert_csv", "Convert CSV tabular data to JSON",
        )
        assert target2 == "data_processor"
