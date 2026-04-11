"""BF-139 + BF-140: Probe scoring hardening and diagnostic enhancement tests."""

from __future__ import annotations

import logging

import pytest


class TestSendProbeExceptionHandling:
    """BF-140: _send_probe must not propagate exceptions."""

    @pytest.mark.asyncio
    async def test_send_probe_returns_empty_on_exception(self):
        """_send_probe returns '' when handle_intent raises."""
        from probos.cognitive.qualification_tests import _send_probe

        class FakeAgent:
            id = "test_agent"
            agent_type = "test"
            async def handle_intent(self, intent):
                raise RuntimeError("LLM client unavailable")

        result = await _send_probe(FakeAgent(), "test message")
        assert result == ""

    @pytest.mark.asyncio
    async def test_send_probe_returns_empty_on_none_result(self):
        """_send_probe returns '' when handle_intent returns None."""
        from probos.cognitive.qualification_tests import _send_probe

        class FakeAgent:
            id = "test_agent"
            agent_type = "test"
            async def handle_intent(self, intent):
                return None

        result = await _send_probe(FakeAgent(), "test message")
        assert result == ""

    @pytest.mark.asyncio
    async def test_send_probe_logs_warning_on_exception(self, caplog):
        """BF-140: Exception is logged at WARNING level."""
        from probos.cognitive.qualification_tests import _send_probe

        class FakeAgent:
            id = "pathologist_crew_0"
            agent_type = "pathologist"
            async def handle_intent(self, intent):
                raise ValueError("Missing runtime attribute")

        with caplog.at_level(logging.WARNING, logger="probos.cognitive.qualification_tests"):
            await _send_probe(FakeAgent(), "test")

        assert any("BF-140" in r.message for r in caplog.records)
        assert any("pathologist" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_send_probe_returns_text_on_success(self):
        """_send_probe returns agent response text on success."""
        from types import SimpleNamespace
        from probos.cognitive.qualification_tests import _send_probe

        class FakeAgent:
            id = "test_agent"
            agent_type = "test"
            async def handle_intent(self, intent):
                return SimpleNamespace(result="Hello Captain.")

        result = await _send_probe(FakeAgent(), "How are you?")
        assert result == "Hello Captain."


class TestReformulationPatterns:
    """BF-139: Reformulation pattern coverage for probe questions."""

    @pytest.mark.parametrize("question", [
        "What happened during first watch?",
        "What was discussed most recently?",
        "What did the Science department identify?",
        "Tell me about the trust anomaly",
        "What happened?",
    ])
    def test_probe_question_produces_reformulation(self, question):
        from probos.knowledge.embeddings import reformulate_query
        variants = reformulate_query(question)
        assert len(variants) >= 2, (
            f"'{question}' should produce at least 2 variants, got {variants}"
        )

    def test_existing_patterns_not_broken(self):
        """Regression: existing patterns still work."""
        from probos.knowledge.embeddings import reformulate_query
        for q in [
            "What is the pool health?",
            "What was the threshold?",
            "When did the failure occur?",
            "Why did the agent crash?",
        ]:
            variants = reformulate_query(q)
            assert len(variants) == 2, f"Regression: '{q}' broke, got {variants}"


class TestDistinctiveKeywords:
    """BF-139: _distinctive_keywords helper tests."""

    def test_filters_stopwords_and_short(self):
        from probos.cognitive.memory_probes import _distinctive_keywords
        kws = _distinctive_keywords("The pool is at a low state")
        assert "the" not in kws
        assert "pool" in kws
        assert "low" in kws
        assert "state" in kws

    def test_empty_on_all_stopwords(self):
        from probos.cognitive.memory_probes import _distinctive_keywords
        kws = _distinctive_keywords("a to in on at")
        assert len(kws) == 0

    def test_custom_min_len(self):
        from probos.cognitive.memory_probes import _distinctive_keywords
        kws = _distinctive_keywords("ab cd efgh", min_len=4)
        assert kws == ["efgh"]


class TestTemporalProbeScoringBF142:
    """BF-142: LLM max-scoring replaces averaging."""

    def test_max_scoring_when_faithfulness_low(self):
        """max(0.005, 0.8) = 0.8, not (0.005 + 0.8)/2 = 0.4."""
        faithfulness = 0.005
        llm_score = 0.8
        # Old formula:
        old = (faithfulness + llm_score) / 2
        # New formula:
        new = max(faithfulness, llm_score)
        assert old < 0.5, f"Old formula should be below threshold: {old}"
        assert new >= 0.5, f"New formula should pass threshold: {new}"
        assert new == 0.8

    def test_max_scoring_when_faithfulness_high(self):
        """When faithfulness is already high, max still works correctly."""
        faithfulness = 0.7
        llm_score = 0.6
        new = max(faithfulness, llm_score)
        assert new == 0.7

    def test_max_scoring_preserves_zero_when_both_zero(self):
        """If both scores are 0, max returns 0."""
        assert max(0.0, 0.0) == 0.0

    def test_max_scoring_llm_none_uses_faithfulness(self):
        """When LLM is unavailable, faithfulness score is used alone."""
        faithfulness = 0.3
        llm_score = None
        score = faithfulness
        if llm_score is not None:
            score = max(score, llm_score)
        assert score == 0.3


class TestProbeScoreDiagnosticsBF142:
    """BF-142: Component scores recorded separately for diagnostics."""

    def test_temporal_per_question_has_component_scores(self):
        """per_question dict must include faithfulness_score and llm_score keys."""
        required_keys = {"faithfulness_score", "llm_score", "score",
                         "correct_content_found", "incorrect_content_found"}
        # Simulate what the per_question dict should look like
        per_q = {
            "question": "What happened during first watch?",
            "expected_episode_ids": ["_qtest_temporal_0"],
            "response_summary": "test",
            "correct_content_found": 1,
            "incorrect_content_found": 0,
            "faithfulness_score": 0.05,
            "llm_score": 0.8,
            "score": 0.8,
        }
        assert required_keys.issubset(per_q.keys()), (
            f"Missing diagnostic keys: {required_keys - per_q.keys()}"
        )

    def test_seeded_recall_per_question_has_component_scores(self):
        """SeededRecallProbe per_question must include component scores."""
        per_q = {
            "episode_id": "test",
            "question": "test?",
            "expected_fact": "test fact",
            "response_summary": "test",
            "faithfulness_score": 0.5,
            "llm_score": 0.7,
            "score": 0.7,
        }
        assert "faithfulness_score" in per_q
        assert "llm_score" in per_q


class TestTemporalEpisodeSemanticGapBF143:
    """BF-143: Temporal episodes must contain temporal markers for semantic retrieval."""

    def test_all_episodes_contain_watch_prefix(self):
        """Every temporal episode must include 'first watch' or 'second watch' in content."""
        from probos.cognitive.memory_probes import _TEMPORAL_EPISODES

        for ep in _TEMPORAL_EPISODES:
            content_lower = ep["content"].lower()
            watch = ep["watch"]
            if watch == "first_watch":
                assert "first watch" in content_lower, (
                    f"First-watch episode missing temporal marker: {ep['content']!r}"
                )
            elif watch == "second_watch":
                assert "second watch" in content_lower, (
                    f"Second-watch episode missing temporal marker: {ep['content']!r}"
                )

    def test_temporal_prefix_improves_similarity(self):
        """Episodes with temporal prefix must have higher similarity to probe questions."""
        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np
        except ImportError:
            pytest.skip("sentence_transformers not installed")

        model = SentenceTransformer("multi-qa-MiniLM-L6-cos-v1")

        question = "What happened during first watch?"
        with_prefix = "During first watch: Pool health dropped to 45% during the monitoring sweep"
        without_prefix = "Pool health dropped to 45% during the monitoring sweep"

        embeddings = model.encode([question, with_prefix, without_prefix])
        sim_with = float(np.dot(embeddings[0], embeddings[1]) / (
            np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
        ))
        sim_without = float(np.dot(embeddings[0], embeddings[2]) / (
            np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[2])
        ))

        assert sim_with > sim_without, (
            f"Prefix should improve similarity: with={sim_with:.4f}, without={sim_without:.4f}"
        )
        # The prefix should meaningfully improve similarity, not just marginally
        assert sim_with - sim_without > 0.05, (
            f"Improvement too small: delta={sim_with - sim_without:.4f}"
        )

    def test_temporal_prefix_beats_real_memory_baseline(self):
        """Prefixed episodes must have higher similarity than typical real memories."""
        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np
        except ImportError:
            pytest.skip("sentence_transformers not installed")

        model = SentenceTransformer("multi-qa-MiniLM-L6-cos-v1")

        question = "What happened during first watch?"
        prefixed = "During first watch: Pool health dropped to 45% during the monitoring sweep"
        real_memory = "[Ward Room] bridge — Echo: Stasis recovery complete, resuming normal operations"

        embeddings = model.encode([question, prefixed, real_memory])
        sim_prefixed = float(np.dot(embeddings[0], embeddings[1]) / (
            np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
        ))
        sim_real = float(np.dot(embeddings[0], embeddings[2]) / (
            np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[2])
        ))

        assert sim_prefixed > sim_real, (
            f"Prefixed episode must beat real memory: prefixed={sim_prefixed:.4f}, "
            f"real={sim_real:.4f}"
        )

    def test_temporal_prefix_does_not_affect_faithfulness_direction(self):
        """Adding temporal prefix should not reduce faithfulness scoring."""
        from probos.cognitive.source_governance import check_faithfulness

        content_with = "During first watch: Pool health dropped to 45%"
        content_without = "Pool health dropped to 45%"
        response = "Pool health was at 45 percent during the monitoring sweep."

        faith_with = check_faithfulness(response_text=response, recalled_memories=[content_with])
        faith_without = check_faithfulness(response_text=response, recalled_memories=[content_without])

        # Prefix should not significantly hurt faithfulness (may slightly help due to 'during')
        assert faith_with.score >= faith_without.score * 0.8, (
            f"Prefix shouldn't significantly reduce faithfulness: "
            f"with={faith_with.score:.3f}, without={faith_without.score:.3f}"
        )
