"""Tests for AD-385: Proactive capability gap prediction."""

import unittest

from probos.cognitive.gap_predictor import (
    CapabilityGapPrediction,
    _extract_topic,
    _get_field,
    predict_gaps,
)


class TestPredictionToDict(unittest.TestCase):
    def test_to_dict(self) -> None:
        p = CapabilityGapPrediction(
            id="gap:test",
            gap_description="Test gap",
            evidence_type="low_confidence",
            evidence_summary="5 episodes",
            evidence_count=5,
            suggested_intent="test_specialist",
            suggested_description="A specialist",
            affected_intent_types=["test"],
            priority="medium",
            created_at=1000.0,
        )
        d = p.to_dict()
        assert d["id"] == "gap:test"
        assert d["gap_description"] == "Test gap"
        assert d["evidence_type"] == "low_confidence"
        assert d["evidence_count"] == 5
        assert d["priority"] == "medium"
        assert d["affected_intent_types"] == ["test"]


class TestLowConfidenceGap(unittest.TestCase):
    def test_low_confidence_gap(self) -> None:
        """6 episodes with avg confidence 0.3 -> prediction with priority medium."""
        episodes = [
            {"agent_type": "a", "intent": "analyze_code", "outcome": {"success": True, "confidence": 0.3}, "timestamp": 1000.0 + i, "error": None}
            for i in range(6)
        ]
        results = predict_gaps(episodes, confidence_threshold=0.4, low_confidence_min_count=5)
        low_conf = [p for p in results if p.evidence_type == "low_confidence"]
        assert len(low_conf) == 1
        assert low_conf[0].priority == "medium"
        assert "analyze_code" in low_conf[0].gap_description

    def test_low_confidence_very_low(self) -> None:
        """avg confidence 0.15 -> priority high."""
        episodes = [
            {"agent_type": "a", "intent": "translate", "outcome": {"success": True, "confidence": 0.15}, "timestamp": 1000.0 + i, "error": None}
            for i in range(6)
        ]
        results = predict_gaps(episodes, confidence_threshold=0.4, low_confidence_min_count=5)
        low_conf = [p for p in results if p.evidence_type == "low_confidence"]
        assert len(low_conf) == 1
        assert low_conf[0].priority == "high"

    def test_low_confidence_below_min_count(self) -> None:
        """Only 3 episodes (min=5) -> no prediction."""
        episodes = [
            {"agent_type": "a", "intent": "analyze_code", "outcome": {"success": True, "confidence": 0.3}, "timestamp": 1000.0 + i, "error": None}
            for i in range(3)
        ]
        results = predict_gaps(episodes, confidence_threshold=0.4, low_confidence_min_count=5)
        low_conf = [p for p in results if p.evidence_type == "low_confidence"]
        assert len(low_conf) == 0

    def test_low_confidence_high_avg(self) -> None:
        """avg confidence 0.8 -> no prediction."""
        episodes = [
            {"agent_type": "a", "intent": "analyze_code", "outcome": {"success": True, "confidence": 0.8}, "timestamp": 1000.0 + i, "error": None}
            for i in range(6)
        ]
        results = predict_gaps(episodes, confidence_threshold=0.4, low_confidence_min_count=5)
        low_conf = [p for p in results if p.evidence_type == "low_confidence"]
        assert len(low_conf) == 0


class TestRepeatedFallback(unittest.TestCase):
    def test_repeated_fallback(self) -> None:
        """4 episodes with no intent, similar text -> fallback prediction."""
        episodes = [
            {"agent_type": "a", "intent": "", "outcome": {"success": False, "confidence": 0.1}, "timestamp": 1000.0 + i, "error": None, "original_text": "Please analyze sentiment of this review"}
            for i in range(4)
        ]
        results = predict_gaps(episodes, fallback_min_count=3)
        fallback = [p for p in results if p.evidence_type == "repeated_fallback"]
        assert len(fallback) == 1
        assert fallback[0].priority == "high"

    def test_repeated_fallback_below_min(self) -> None:
        """Only 2 episodes -> no prediction."""
        episodes = [
            {"agent_type": "a", "intent": "", "outcome": {"success": False, "confidence": 0.1}, "timestamp": 1000.0 + i, "error": None, "original_text": "Analyze sentiment please"}
            for i in range(2)
        ]
        results = predict_gaps(episodes, fallback_min_count=3)
        fallback = [p for p in results if p.evidence_type == "repeated_fallback"]
        assert len(fallback) == 0


class TestPartialDagCoverage(unittest.TestCase):
    def test_partial_dag_coverage(self) -> None:
        """DAG node fails 4/5 times -> partial coverage prediction."""
        episodes = [
            {"agent_type": "a", "intent": "step_a", "outcome": {"success": False, "confidence": 0.3}, "timestamp": 1000.0, "error": "fail", "dag_id": "dag1", "dag_node_id": "parse_input"},
            {"agent_type": "a", "intent": "step_a", "outcome": {"success": False, "confidence": 0.2}, "timestamp": 1001.0, "error": "fail", "dag_id": "dag2", "dag_node_id": "parse_input"},
            {"agent_type": "a", "intent": "step_a", "outcome": {"success": False, "confidence": 0.1}, "timestamp": 1002.0, "error": "fail", "dag_id": "dag3", "dag_node_id": "parse_input"},
            {"agent_type": "a", "intent": "step_a", "outcome": {"success": False, "confidence": 0.2}, "timestamp": 1003.0, "error": "fail", "dag_id": "dag4", "dag_node_id": "parse_input"},
            {"agent_type": "a", "intent": "step_a", "outcome": {"success": True, "confidence": 0.8}, "timestamp": 1004.0, "error": None, "dag_id": "dag5", "dag_node_id": "parse_input"},
        ]
        results = predict_gaps(episodes)
        partial = [p for p in results if p.evidence_type == "partial_coverage"]
        assert len(partial) == 1
        assert "parse_input" in partial[0].gap_description
        assert partial[0].priority == "high"  # 80% failure

    def test_partial_dag_low_failure(self) -> None:
        """Node fails 1/5 -> no prediction (below 50%)."""
        episodes = [
            {"agent_type": "a", "intent": "step_a", "outcome": {"success": True, "confidence": 0.9}, "timestamp": 1000.0 + i, "error": None, "dag_id": f"dag{i}", "dag_node_id": "parse_input"}
            for i in range(4)
        ] + [
            {"agent_type": "a", "intent": "step_a", "outcome": {"success": False, "confidence": 0.1}, "timestamp": 1005.0, "error": "fail", "dag_id": "dag5", "dag_node_id": "parse_input"},
        ]
        results = predict_gaps(episodes)
        partial = [p for p in results if p.evidence_type == "partial_coverage"]
        assert len(partial) == 0

    def test_partial_dag_insufficient_attempts(self) -> None:
        """Only 2 attempts -> no prediction (need 3+)."""
        episodes = [
            {"agent_type": "a", "intent": "step_a", "outcome": {"success": False, "confidence": 0.1}, "timestamp": 1000.0, "error": "fail", "dag_id": "dag1", "dag_node_id": "parse_input"},
            {"agent_type": "a", "intent": "step_a", "outcome": {"success": False, "confidence": 0.1}, "timestamp": 1001.0, "error": "fail", "dag_id": "dag2", "dag_node_id": "parse_input"},
        ]
        results = predict_gaps(episodes)
        partial = [p for p in results if p.evidence_type == "partial_coverage"]
        assert len(partial) == 0


class TestExtractTopic(unittest.TestCase):
    def test_extract_topic(self) -> None:
        assert _extract_topic("How do I analyze Python code?") == "analyze python code"

    def test_extract_topic_short(self) -> None:
        assert _extract_topic("help") == "help"


class TestEmptyAndGetField(unittest.TestCase):
    def test_empty_episodes(self) -> None:
        results = predict_gaps([], low_confidence_min_count=5, fallback_min_count=3)
        assert results == []

    def test_get_field_dict_and_object(self) -> None:
        d = {"intent": "read_file"}
        assert _get_field(d, "intent", "") == "read_file"
        assert _get_field(d, "missing", "default") == "default"

        class Obj:
            intent = "analyze"
        assert _get_field(Obj(), "intent", "") == "analyze"
        assert _get_field(Obj(), "missing", "default") == "default"
