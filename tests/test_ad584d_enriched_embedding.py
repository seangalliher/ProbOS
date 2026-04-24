"""Tests for AD-584d: Enriched embedding document with reflection + question seeding."""

from __future__ import annotations

import pytest
from probos.types import Episode, AnchorFrame
from probos.cognitive.episodic import EpisodicMemory


# --- _prepare_document tests ---

class TestPrepareDocument:

    def test_includes_user_input(self):
        """Embedding document includes user_input."""
        ep = Episode(user_input="test query")
        doc = EpisodicMemory._prepare_document(ep)
        assert "test query" in doc

    def test_includes_reflection(self):
        """AD-584d: Embedding document now includes reflection."""
        ep = Episode(user_input="test query", reflection="This was caused by a routing failure.")
        doc = EpisodicMemory._prepare_document(ep)
        assert "routing failure" in doc

    def test_includes_anchors(self):
        """Anchor metadata still included (AD-605 preserved)."""
        ep = Episode(
            user_input="test",
            anchors=AnchorFrame(department="engineering", channel="eng-ops"),
        )
        doc = EpisodicMemory._prepare_document(ep)
        assert "[engineering]" in doc
        assert "[eng-ops]" in doc

    def test_no_reflection_still_works(self):
        """Episodes without reflection produce valid documents."""
        ep = Episode(user_input="test query", reflection=None)
        doc = EpisodicMemory._prepare_document(ep)
        assert "test query" in doc
        assert "None" not in doc

    def test_empty_episode(self):
        """Totally empty episode produces non-empty document (question seeds may apply)."""
        ep = Episode()
        doc = EpisodicMemory._prepare_document(ep)
        # Should not crash
        assert isinstance(doc, str)

    def test_alignment_with_fts5(self):
        """AD-584d: Embedding document contains same content as FTS5 index."""
        ep = Episode(user_input="hello world", reflection="this was important")
        doc = EpisodicMemory._prepare_document(ep)
        fts_content = (ep.user_input or "") + " " + (ep.reflection or "")
        # Both user_input and reflection should be in the embedding doc
        assert "hello world" in doc
        assert "this was important" in doc


# --- Question seed tests ---

class TestQuestionSeeds:

    def test_intent_based_question(self):
        """Intent from dag_summary produces a question."""
        ep = Episode(dag_summary={"intent": "code_review"})
        questions = EpisodicMemory._generate_question_seeds(ep)
        assert any("code_review" in q for q in questions)

    def test_outcome_based_question(self):
        """Outcomes produce a result-specific question."""
        ep = Episode(
            dag_summary={"intent": "build"},
            outcomes=[{"result": "compilation_failed"}],
        )
        questions = EpisodicMemory._generate_question_seeds(ep)
        assert any("compilation_failed" in q for q in questions)

    def test_department_based_question(self):
        """Department question generated when no intent available."""
        ep = Episode(anchors=AnchorFrame(department="medical"))
        questions = EpisodicMemory._generate_question_seeds(ep)
        assert any("medical" in q for q in questions)

    def test_no_department_question_when_intent_exists(self):
        """Department question NOT generated when intent question exists."""
        ep = Episode(
            dag_summary={"intent": "code_review_xyz"},
            anchors=AnchorFrame(department="medical"),
        )
        questions = EpisodicMemory._generate_question_seeds(ep)
        # Should have intent question, not department question
        assert any("code_review_xyz" in q for q in questions)
        assert not any("medical" in q for q in questions)

    def test_max_three_questions(self):
        """Question seeds capped at 3."""
        ep = Episode(
            dag_summary={"intent": "build"},
            outcomes=[{"result": "ok"}],
            anchors=AnchorFrame(department="engineering"),
        )
        questions = EpisodicMemory._generate_question_seeds(ep)
        assert len(questions) <= 3

    def test_empty_episode_no_questions(self):
        """Empty episode produces no questions."""
        ep = Episode()
        questions = EpisodicMemory._generate_question_seeds(ep)
        assert questions == []

    def test_reflection_not_templated_into_question(self):
        """AD-584d: Reflection is NOT used for question generation (grammar issues)."""
        ep = Episode(reflection="The trust cascade dampened too aggressively. This needs tuning.")
        questions = EpisodicMemory._generate_question_seeds(ep)
        # No questions should be generated from reflection alone
        assert questions == []

    def test_questions_in_document(self):
        """Question seeds appear in the prepared document."""
        ep = Episode(
            user_input="test",
            dag_summary={"intent": "analyze"},
        )
        doc = EpisodicMemory._prepare_document(ep)
        assert "[Questions:" in doc
        assert "analyze" in doc

    def test_no_questions_no_tag(self):
        """No [Questions:] tag when no questions generated."""
        ep = Episode(user_input="test")
        doc = EpisodicMemory._prepare_document(ep)
        assert "[Questions:" not in doc
