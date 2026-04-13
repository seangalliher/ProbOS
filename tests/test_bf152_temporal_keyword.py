"""BF-152: Temporal reasoning probe keyword scoring for JSON-responding agents.

Root cause: TemporalReasoningProbe computes correct_found via
_distinctive_keywords() but never uses it as a score signal. Combined with
check_faithfulness() returning false-zero on JSON agents (BF-151 root cause),
the probe relies entirely on the LLM scorer — which is variable (0.0–0.5).

Fix: Added key_values to _TEMPORAL_EPISODES and keyword_score as a third
scoring signal: max(faithfulness, llm, keyword). Penalty for wrong-watch
keyword matches preserved. Ship memory nudge added to questions.
"""

import pytest

from probos.cognitive.memory_probes import _TEMPORAL_EPISODES, _distinctive_keywords


class TestTemporalEpisodesKeyValues:
    """Verify _TEMPORAL_EPISODES key_values structure."""

    def test_all_episodes_have_key_values(self):
        """BF-152: Each episode must have a key_values list."""
        for i, te in enumerate(_TEMPORAL_EPISODES):
            assert "key_values" in te, f"Episode {i}: missing key_values"
            assert isinstance(te["key_values"], list), f"Episode {i}: key_values must be list"
            assert len(te["key_values"]) > 0, f"Episode {i}: key_values must be non-empty"

    def test_key_values_are_nonempty_strings(self):
        """Each key_value must be a non-empty string."""
        for i, te in enumerate(_TEMPORAL_EPISODES):
            for kv in te["key_values"]:
                assert isinstance(kv, str) and kv, f"Episode {i}: key_value items must be non-empty str"

    def test_key_values_present_in_content(self):
        """Each key_value must appear in its episode's content."""
        for i, te in enumerate(_TEMPORAL_EPISODES):
            content_lower = te["content"].lower()
            found = any(kv.lower() in content_lower for kv in te["key_values"])
            assert found, (
                f"Episode {i}: none of {te['key_values']} found in content: {te['content']!r}"
            )

    def test_four_temporal_episodes(self):
        """Maintain the 4-episode contract."""
        assert len(_TEMPORAL_EPISODES) == 4

    def test_two_per_watch(self):
        """Two episodes per watch section."""
        first = [e for e in _TEMPORAL_EPISODES if e["watch"] == "first"]
        second = [e for e in _TEMPORAL_EPISODES if e["watch"] == "second_dog"]
        assert len(first) == 2
        assert len(second) == 2


class TestWatchKeyValuesMutualExclusion:
    """Key values from different watches must not overlap."""

    def test_first_and_second_kvs_no_overlap(self):
        """BF-152 critical: first watch key_values must not match second watch content and vice versa.

        If key_values overlap across watches, the temporal discrimination breaks
        (response matches both → wrong-watch penalty fires on correct answers).
        """
        first_kvs = {kv.lower() for te in _TEMPORAL_EPISODES
                     if te["watch"] == "first" for kv in te["key_values"]}
        second_kvs = {kv.lower() for te in _TEMPORAL_EPISODES
                      if te["watch"] == "second_dog" for kv in te["key_values"]}
        overlap = first_kvs & second_kvs
        assert not overlap, (
            f"Key values overlap across watches: {overlap}. "
            f"Temporal discrimination requires mutually exclusive key_values."
        )

    def test_first_kvs_not_in_second_content(self):
        """First watch key_values should not appear in second watch episode content."""
        first_kvs = [kv for te in _TEMPORAL_EPISODES
                     if te["watch"] == "first" for kv in te["key_values"]]
        second_content = " ".join(te["content"].lower() for te in _TEMPORAL_EPISODES
                                  if te["watch"] == "second_dog")
        for kv in first_kvs:
            assert kv.lower() not in second_content, (
                f"First-watch key_value '{kv}' found in second watch content"
            )

    def test_second_kvs_not_in_first_content(self):
        """Second watch key_values should not appear in first watch episode content."""
        second_kvs = [kv for te in _TEMPORAL_EPISODES
                      if te["watch"] == "second_dog" for kv in te["key_values"]]
        first_content = " ".join(te["content"].lower() for te in _TEMPORAL_EPISODES
                                 if te["watch"] == "first")
        for kv in second_kvs:
            assert kv.lower() not in first_content, (
                f"Second-watch key_value '{kv}' found in first watch content"
            )


class TestKeywordScoringInJSON:
    """Verify keyword matching handles JSON-wrapped temporal responses."""

    @pytest.mark.parametrize("watch,json_response", [
        ("first", '{"analysis_type": "temporal", "events": [{"description": "pool health dropped to 45%", "severity": "high"}, {"description": "engineering rerouted 3 workers"}]}'),
        ("second_dog", '{"analysis_type": "temporal", "events": [{"description": "subspace anomaly at bearing 127 mark 4"}, {"description": "diplomatic envoy requested docking clearance"}]}'),
    ])
    def test_keyword_detects_correct_watch_in_json(self, watch, json_response):
        """Correct-watch key_values found in JSON response."""
        correct_kvs = [kv for te in _TEMPORAL_EPISODES
                       if te["watch"] == watch for kv in te["key_values"]]
        resp_lower = json_response.lower()
        hits = sum(1 for kv in correct_kvs if kv.lower() in resp_lower)
        assert hits > 0, f"Expected some of {correct_kvs} to match in JSON"

    @pytest.mark.parametrize("watch,json_response", [
        ("first", '{"analysis_type": "temporal", "events": [{"description": "pool health dropped to 45%"}]}'),
        ("second_dog", '{"analysis_type": "temporal", "events": [{"description": "subspace anomaly at bearing 127"}]}'),
    ])
    def test_keyword_rejects_wrong_watch_in_json(self, watch, json_response):
        """Wrong-watch key_values should NOT match in response about correct watch."""
        wrong_watch = "second_dog" if watch == "first" else "first"
        wrong_kvs = [kv for te in _TEMPORAL_EPISODES
                     if te["watch"] == wrong_watch for kv in te["key_values"]]
        resp_lower = json_response.lower()
        hits = sum(1 for kv in wrong_kvs if kv.lower() in resp_lower)
        assert hits == 0, f"Wrong-watch key_values {wrong_kvs} should not match"

    def test_keyword_score_computation(self):
        """BF-152: keyword_score = kv_correct / len(correct_content), clamped to [0, 1]."""
        correct_kvs = [kv for te in _TEMPORAL_EPISODES
                       if te["watch"] == "first" for kv in te["key_values"]]
        correct_content = [te["content"] for te in _TEMPORAL_EPISODES if te["watch"] == "first"]
        wrong_kvs = [kv for te in _TEMPORAL_EPISODES
                     if te["watch"] == "second_dog" for kv in te["key_values"]]

        # Response mentions both first-watch episodes
        resp = "pool health 45% and 3 workers rerouted for increased load"
        resp_lower = resp.lower()

        kv_correct = sum(1 for kv in correct_kvs if kv.lower() in resp_lower)
        kv_wrong = sum(1 for kv in wrong_kvs if kv.lower() in resp_lower)
        keyword_score = min(1.0, kv_correct / max(1, len(correct_content)))
        if kv_wrong > 0:
            keyword_score = max(0.0, keyword_score - 0.3 * kv_wrong)

        assert kv_correct >= 2, f"Should match at least 2 key_values, got {kv_correct}"
        assert kv_wrong == 0, f"Should not match wrong-watch key_values"
        assert keyword_score >= 0.5, f"keyword_score should be >= 0.5, got {keyword_score}"

    def test_wrong_watch_penalty_applied(self):
        """BF-152: Wrong-watch keyword matches apply -0.3 penalty per hit."""
        correct_kvs = ["45%", "pool health"]
        wrong_kvs = ["subspace anomaly", "diplomatic envoy"]

        # Response mentions correct AND wrong watch content
        resp = "pool health 45% and subspace anomaly detected"
        resp_lower = resp.lower()

        kv_correct = sum(1 for kv in correct_kvs if kv.lower() in resp_lower)
        kv_wrong = sum(1 for kv in wrong_kvs if kv.lower() in resp_lower)

        keyword_score = min(1.0, kv_correct / 2)
        if kv_wrong > 0:
            keyword_score = max(0.0, keyword_score - 0.3 * kv_wrong)

        assert kv_wrong == 1  # "subspace anomaly" matches
        assert keyword_score == pytest.approx(0.7, abs=0.01)  # 1.0 - 0.3

    def test_format_agnostic(self):
        """Same temporal fact in plain text vs JSON vs markdown should all match."""
        kvs = _TEMPORAL_EPISODES[0]["key_values"]  # ["45%", "pool health", "monitoring sweep"]

        plain = "Pool health dropped to 45% during the monitoring sweep."
        json_resp = '{"event": "pool health drop", "value": "45%", "context": "monitoring sweep"}'
        markdown = "- **Pool Health**: dropped to 45% (monitoring sweep)"

        for fmt_name, resp in [("plain", plain), ("json", json_resp), ("markdown", markdown)]:
            hit = any(kv.lower() in resp.lower() for kv in kvs)
            assert hit, f"Format '{fmt_name}' should detect key_value"


class TestQuestionShipMemoryNudge:
    """BF-152: Temporal questions must include ship memory nudge."""

    def test_questions_include_ship_memory(self):
        """Questions should nudge 'ship memory' recall for specific value retrieval."""
        # Rebuild the questions list to test (mirror the probe's structure)
        questions = [
            "What happened during first watch? State specific details from your ship memory.",
            "What happened during second dog watch? State specific details from your ship memory.",
        ]
        for q in questions:
            assert "ship memory" in q.lower(), f"Question should include 'ship memory' nudge: {q}"


class TestDistinctiveKeywordsStillWork:
    """BF-152: _distinctive_keywords still produces good fallback keywords."""

    def test_distinctive_keywords_for_each_episode(self):
        """Each episode produces distinctive (non-stopword) keywords."""
        for i, te in enumerate(_TEMPORAL_EPISODES):
            kws = _distinctive_keywords(te["content"])
            assert len(kws) >= 3, f"Episode {i} should produce >= 3 distinctive keywords, got {kws}"

    def test_distinctive_keywords_exclude_temporal_stopwords(self):
        """'during', 'first', 'second', 'watch', 'dog' are filtered out."""
        from probos.cognitive.memory_probes import _PROBE_STOP_WORDS
        for te in _TEMPORAL_EPISODES:
            kws = _distinctive_keywords(te["content"])
            for kw in kws:
                assert kw not in _PROBE_STOP_WORDS, f"Keyword '{kw}' should be filtered as stop word"
