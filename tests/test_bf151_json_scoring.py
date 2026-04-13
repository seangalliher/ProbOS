"""BF-151: Seeded recall probe keyword scoring for JSON-responding agents.
BF-151b: Knowledge update probe alias-based value detection.

Root cause: check_faithfulness() token-overlap scoring produces false-zero
on agents that wrap responses in JSON format. JSON structural tokens
(analysis_type, patterns_identified, confidence, etc.) dilute the overlap
ratio, even when the actual fact IS present in the response.

Fix: Added key_values to _RECALL_FACTS (3-tuple) and keyword_score as a
third scoring signal: max(faithfulness, llm, keyword).

BF-151b fix: Added old_aliases / new_aliases to _UPDATE_PAIRS for
format-agnostic value detection in knowledge_update_probe. Aliases must
be mutually exclusive (no alias appears in both old and new lists) to
preserve the recency-preference discriminator.
"""

import pytest

from probos.cognitive.memory_probes import _RECALL_FACTS, _UPDATE_PAIRS


class TestRecallFactsStructure:
    """Verify _RECALL_FACTS 3-tuple format is intact."""

    def test_recall_facts_are_3_tuples(self):
        """BF-151: Each entry must be (fact, question, key_values)."""
        for i, entry in enumerate(_RECALL_FACTS):
            assert len(entry) == 3, f"Entry {i} has {len(entry)} elements, expected 3"
            fact, question, key_values = entry
            assert isinstance(fact, str) and fact, f"Entry {i}: fact must be non-empty str"
            assert isinstance(question, str) and question, f"Entry {i}: question must be non-empty str"
            assert isinstance(key_values, list) and key_values, f"Entry {i}: key_values must be non-empty list"
            for kv in key_values:
                assert isinstance(kv, str) and kv, f"Entry {i}: key_value items must be non-empty str"

    def test_key_values_present_in_fact(self):
        """Each key_value must actually appear in the corresponding fact."""
        for i, (fact, _q, key_values) in enumerate(_RECALL_FACTS):
            fact_lower = fact.lower()
            found = any(kv.lower() in fact_lower for kv in key_values)
            assert found, (
                f"Entry {i}: none of {key_values} found in fact: {fact!r}"
            )

    def test_five_recall_facts(self):
        """Maintain the 5-fact contract."""
        assert len(_RECALL_FACTS) == 5

    def test_question_includes_ship_memory_nudge(self):
        """BF-151 option D: questions must nudge specific value retrieval."""
        for i, (_f, question, _kv) in enumerate(_RECALL_FACTS):
            assert "ship memory" in question.lower(), (
                f"Entry {i}: question should nudge 'ship memory' recall"
            )


class TestKeywordScoring:
    """Verify keyword matching logic handles JSON-wrapped responses."""

    @pytest.mark.parametrize("i,json_response", [
        (0, '{"analysis_type": "synthesis", "patterns_identified": [{"description": "pool health threshold at 0.7", "confidence": 0.8}]}'),
        (1, '{"analysis_type": "emergence", "patterns_identified": [{"description": "trust anomaly detected at 14:32", "confidence": 0.9}]}'),
        (2, '{"analysis_type": "advisory", "recommendations": ["cooldown of 45 minutes recommended"]}'),
        (3, '{"analysis_type": "synthesis", "patterns_identified": [{"description": "Hebbian weight reached 0.92", "confidence": 0.95}]}'),
        (4, '{"analysis_type": "emergence", "patterns_identified": [{"description": "three convergence events in dog watch", "confidence": 0.7}]}'),
    ])
    def test_keyword_detects_fact_in_json(self, i, json_response):
        """Key values found even when wrapped in JSON structure."""
        _fact, _question, key_values = _RECALL_FACTS[i]
        resp_lower = json_response.lower()
        assert any(kv.lower() in resp_lower for kv in key_values), (
            f"Expected key_values {key_values} to match in JSON response"
        )

    @pytest.mark.parametrize("i,wrong_response", [
        (0, '{"analysis_type": "synthesis", "patterns_identified": [{"description": "pool health normal"}]}'),
        (1, '{"analysis_type": "emergence", "patterns_identified": [{"description": "no anomalies found"}]}'),
        (2, '{"analysis_type": "advisory", "recommendations": ["standard cooldown period"]}'),
        (3, '{"analysis_type": "synthesis", "patterns_identified": [{"description": "Hebbian weights nominal"}]}'),
        (4, '{"analysis_type": "emergence", "patterns_identified": [{"description": "convergence patterns stable"}]}'),
    ])
    def test_keyword_rejects_wrong_response(self, i, wrong_response):
        """Wrong responses that don't contain key values should NOT match."""
        _fact, _question, key_values = _RECALL_FACTS[i]
        resp_lower = wrong_response.lower()
        assert not any(kv.lower() in resp_lower for kv in key_values), (
            f"Key values {key_values} should NOT match in wrong response"
        )

    def test_keyword_score_is_format_agnostic(self):
        """Same fact in plain text vs JSON should produce same keyword_hit."""
        fact, _q, key_values = _RECALL_FACTS[0]  # "0.7" threshold

        plain = "The pool health threshold is currently set to 0.7."
        json_resp = '{"threshold": 0.7, "status": "configured"}'
        markdown = "- **Pool Health**: 0.7 (configured this session)"

        for fmt_name, resp in [("plain", plain), ("json", json_resp), ("markdown", markdown)]:
            hit = any(kv.lower() in resp.lower() for kv in key_values)
            assert hit, f"Format '{fmt_name}' should produce keyword hit"


class TestRecallFactsBackwardCompatibility:
    """Ensure existing code patterns still work with 3-tuple structure."""

    def test_unpack_fact_question_keyvalues(self):
        """Standard 3-tuple unpacking works."""
        for fact, question, key_values in _RECALL_FACTS:
            assert fact
            assert question
            assert key_values

    def test_enumerate_unpack(self):
        """Enumerate + unpack pattern used in _run_inner."""
        for i, (fact, question, key_values) in enumerate(_RECALL_FACTS):
            assert isinstance(i, int)
            assert fact
            assert question
            assert key_values

    def test_episode_creation_unpack(self):
        """Episode creation uses (fact, _, _kv) pattern."""
        for i, (fact, _, _kv) in enumerate(_RECALL_FACTS):
            assert fact  # fact is used for episode content


# ===================================================================
# BF-151b: Knowledge update probe alias-based value detection tests
# ===================================================================


class TestUpdatePairsStructure:
    """Verify _UPDATE_PAIRS alias format is intact."""

    def test_update_pairs_have_aliases(self):
        """BF-151b: Each pair must have old_aliases and new_aliases lists."""
        for i, pair in enumerate(_UPDATE_PAIRS):
            assert "old_aliases" in pair, f"Pair {i}: missing old_aliases"
            assert "new_aliases" in pair, f"Pair {i}: missing new_aliases"
            assert isinstance(pair["old_aliases"], list), f"Pair {i}: old_aliases must be list"
            assert isinstance(pair["new_aliases"], list), f"Pair {i}: new_aliases must be list"
            assert len(pair["old_aliases"]) > 0, f"Pair {i}: old_aliases must be non-empty"
            assert len(pair["new_aliases"]) > 0, f"Pair {i}: new_aliases must be non-empty"

    def test_aliases_are_nonempty_strings(self):
        """Each alias must be a non-empty string."""
        for i, pair in enumerate(_UPDATE_PAIRS):
            for alias in pair["old_aliases"]:
                assert isinstance(alias, str) and alias, f"Pair {i}: old alias must be non-empty str"
            for alias in pair["new_aliases"]:
                assert isinstance(alias, str) and alias, f"Pair {i}: new alias must be non-empty str"

    def test_aliases_mutually_exclusive(self):
        """BF-151b critical: old and new aliases must NOT overlap.

        If the same alias appears in both sets, the recency-preference
        discriminator breaks (response matches both → score 0.5 → ambiguous).
        """
        for i, pair in enumerate(_UPDATE_PAIRS):
            old_set = {a.lower() for a in pair["old_aliases"]}
            new_set = {a.lower() for a in pair["new_aliases"]}
            overlap = old_set & new_set
            assert not overlap, (
                f"Pair {i} ({pair['topic']}): aliases overlap: {overlap}. "
                f"Old and new aliases must be mutually exclusive."
            )

    def test_old_value_in_old_aliases(self):
        """The canonical old_value must appear in old_aliases."""
        for i, pair in enumerate(_UPDATE_PAIRS):
            old_lower = {a.lower() for a in pair["old_aliases"]}
            assert pair["old_value"].lower() in old_lower, (
                f"Pair {i}: old_value '{pair['old_value']}' not in old_aliases"
            )

    def test_new_value_in_new_aliases(self):
        """The canonical new_value must appear in new_aliases."""
        for i, pair in enumerate(_UPDATE_PAIRS):
            new_lower = {a.lower() for a in pair["new_aliases"]}
            assert pair["new_value"].lower() in new_lower, (
                f"Pair {i}: new_value '{pair['new_value']}' not in new_aliases"
            )

    def test_question_includes_ship_memory_nudge(self):
        """BF-151b: questions must nudge specific value retrieval."""
        for i, pair in enumerate(_UPDATE_PAIRS):
            assert "ship memory" in pair["question"].lower(), (
                f"Pair {i}: question should nudge 'ship memory' recall"
            )

    def test_two_update_pairs(self):
        """Maintain the 2-pair contract."""
        assert len(_UPDATE_PAIRS) == 2


class TestAliasDetectionInJSON:
    """Verify alias matching handles JSON-wrapped responses."""

    @pytest.mark.parametrize("i,json_new_response", [
        (0, '{"analysis_type": "configuration", "current_value": 0.5, "status": "updated"}'),
        (1, '{"analysis_type": "configuration", "cooldown": "60 minutes", "status": "changed"}'),
    ])
    def test_new_alias_detected_in_json(self, i, json_new_response):
        """New aliases found in JSON response → should score 1.0 (has_new, not has_old)."""
        pair = _UPDATE_PAIRS[i]
        resp_lower = json_new_response.lower()
        new_aliases = pair.get("new_aliases", [pair["new_value"]])
        old_aliases = pair.get("old_aliases", [pair["old_value"]])
        has_new = any(a.lower() in resp_lower for a in new_aliases)
        has_old = any(a.lower() in resp_lower for a in old_aliases)
        assert has_new, f"Expected new_aliases {new_aliases} to match in JSON"
        assert not has_old, f"Expected old_aliases {old_aliases} NOT to match in JSON"

    @pytest.mark.parametrize("i,json_old_response", [
        (0, '{"analysis_type": "configuration", "current_value": 0.3, "status": "stale"}'),
        (1, '{"analysis_type": "configuration", "cooldown": "30 minutes", "status": "stale"}'),
    ])
    def test_old_alias_detected_in_json(self, i, json_old_response):
        """Old aliases found in JSON response → should score 0.0 (has_old, not has_new)."""
        pair = _UPDATE_PAIRS[i]
        resp_lower = json_old_response.lower()
        new_aliases = pair.get("new_aliases", [pair["new_value"]])
        old_aliases = pair.get("old_aliases", [pair["old_value"]])
        has_new = any(a.lower() in resp_lower for a in new_aliases)
        has_old = any(a.lower() in resp_lower for a in old_aliases)
        assert has_old, f"Expected old_aliases {old_aliases} to match in JSON"
        assert not has_new, f"Expected new_aliases {new_aliases} NOT to match in JSON"

    @pytest.mark.parametrize("i,json_neither_response", [
        (0, '{"analysis_type": "configuration", "status": "unknown", "threshold": "not configured"}'),
        (1, '{"analysis_type": "configuration", "status": "unknown", "cooldown": "not configured"}'),
    ])
    def test_neither_alias_in_json(self, i, json_neither_response):
        """No aliases found → has_new=False, has_old=False → score 0.5 (ambiguous)."""
        pair = _UPDATE_PAIRS[i]
        resp_lower = json_neither_response.lower()
        new_aliases = pair.get("new_aliases", [pair["new_value"]])
        old_aliases = pair.get("old_aliases", [pair["old_value"]])
        has_new = any(a.lower() in resp_lower for a in new_aliases)
        has_old = any(a.lower() in resp_lower for a in old_aliases)
        assert not has_new, f"New aliases should NOT match in ambiguous response"
        assert not has_old, f"Old aliases should NOT match in ambiguous response"

    def test_alias_fallback_to_value(self):
        """When aliases key is missing, falls back to old_value/new_value."""
        pair_no_aliases = {
            "old_value": "0.3",
            "new_value": "0.5",
        }
        resp = "the threshold is 0.5"
        new_aliases = pair_no_aliases.get("new_aliases", [pair_no_aliases["new_value"]])
        old_aliases = pair_no_aliases.get("old_aliases", [pair_no_aliases["old_value"]])
        has_new = any(a.lower() in resp.lower() for a in new_aliases)
        has_old = any(a.lower() in resp.lower() for a in old_aliases)
        assert has_new
        assert not has_old

    def test_alias_format_agnostic(self):
        """Same updated value in plain text vs JSON vs markdown should all match."""
        pair = _UPDATE_PAIRS[1]  # cooldown: 30→60
        new_aliases = pair["new_aliases"]

        plain = "The agent cooldown has been changed to 60 minutes."
        json_resp = '{"cooldown_minutes": 60, "status": "updated"}'
        markdown = "- **Cooldown**: 60 min (recently updated)"

        for fmt_name, resp in [("plain", plain), ("json", json_resp), ("markdown", markdown)]:
            hit = any(a.lower() in resp.lower() for a in new_aliases)
            assert hit, f"Format '{fmt_name}' should detect new alias"
