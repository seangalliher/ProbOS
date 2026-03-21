"""Tests for AD-383: Strategy extraction from episodic memory."""

import unittest

from probos.cognitive.strategy_extraction import (
    StrategyPattern,
    StrategyType,
    _get_field,
    extract_strategies,
)


class TestStrategyPatternMakeId(unittest.TestCase):
    def test_make_id(self) -> None:
        sid = StrategyPattern.make_id("error_recovery", "Recovery from: timeout")
        assert isinstance(sid, str)
        assert len(sid) == 16

    def test_make_id_deterministic(self) -> None:
        a = StrategyPattern.make_id("error_recovery", "Recovery from: timeout")
        b = StrategyPattern.make_id("error_recovery", "Recovery from: timeout")
        assert a == b


class TestStrategyPatternReinforce(unittest.TestCase):
    def test_reinforce(self) -> None:
        sp = StrategyPattern(
            id="abc123",
            strategy_type=StrategyType.ERROR_RECOVERY,
            description="test",
            applicability="test",
            source_agents=["a"],
            source_intent_types=["i"],
            evidence_count=1,
            confidence=0.5,
        )
        sp.reinforce(2)
        assert sp.evidence_count == 3
        assert sp.confidence > 0.5
        assert sp.confidence <= 1.0
        # confidence = 1 - 1/(3+1) = 0.75
        assert abs(sp.confidence - 0.75) < 0.01


class TestStrategyPatternRoundtrip(unittest.TestCase):
    def test_roundtrip(self) -> None:
        sp = StrategyPattern(
            id="abc123",
            strategy_type=StrategyType.PROMPT_TECHNIQUE,
            description="High-confidence approach for read_file",
            applicability="When handling read_file intents",
            source_agents=["file_reader", "code_analyzer"],
            source_intent_types=["read_file"],
            evidence_count=5,
            confidence=0.9,
            created_at=1000.0,
            updated_at=2000.0,
        )
        d = sp.to_dict()
        sp2 = StrategyPattern.from_dict(d)
        assert sp2.id == sp.id
        assert sp2.strategy_type == sp.strategy_type
        assert sp2.description == sp.description
        assert sp2.applicability == sp.applicability
        assert sp2.source_agents == sp.source_agents
        assert sp2.source_intent_types == sp.source_intent_types
        assert sp2.evidence_count == sp.evidence_count
        assert sp2.confidence == sp.confidence
        assert sp2.created_at == sp.created_at
        assert sp2.updated_at == sp.updated_at


class TestExtractErrorRecovery(unittest.TestCase):
    def _make_error_episodes(self) -> list[dict]:
        """5 episodes: 3 agent types, same error, 1 has recovery."""
        base = "Connection timeout to api.example.com"
        return [
            {"agent_type": "file_reader", "intent": "read_file", "outcome": {"success": False, "confidence": 0.2}, "timestamp": 1000.0, "error": base},
            {"agent_type": "http_fetch", "intent": "fetch_url", "outcome": {"success": False, "confidence": 0.1}, "timestamp": 1001.0, "error": base},
            {"agent_type": "code_analyzer", "intent": "analyze", "outcome": {"success": True, "confidence": 0.8}, "timestamp": 1002.0, "error": base},
            {"agent_type": "file_reader", "intent": "read_file", "outcome": {"success": False, "confidence": 0.3}, "timestamp": 1003.0, "error": base},
            {"agent_type": "http_fetch", "intent": "fetch_url", "outcome": {"success": False, "confidence": 0.1}, "timestamp": 1004.0, "error": base},
        ]

    def test_extract_error_recovery_cross_agent(self) -> None:
        episodes = self._make_error_episodes()
        results = extract_strategies(episodes, min_occurrences=3)
        error_strategies = [s for s in results if s.strategy_type == StrategyType.ERROR_RECOVERY]
        assert len(error_strategies) == 1
        s = error_strategies[0]
        assert "Connection timeout" in s.description
        assert len(s.source_agents) >= 2
        assert s.evidence_count == 5

    def test_extract_error_recovery_single_agent_no_match(self) -> None:
        episodes = [
            {"agent_type": "file_reader", "intent": "read_file", "outcome": {"success": False}, "timestamp": 1000.0, "error": "Disk full"},
            {"agent_type": "file_reader", "intent": "read_file", "outcome": {"success": False}, "timestamp": 1001.0, "error": "Disk full"},
            {"agent_type": "file_reader", "intent": "read_file", "outcome": {"success": True}, "timestamp": 1002.0, "error": "Disk full"},
        ]
        results = extract_strategies(episodes, min_occurrences=3)
        # Only 1 agent type — no strategy (requires 2+)
        assert len(results) == 0

    def test_extract_error_recovery_below_min_occurrences(self) -> None:
        episodes = [
            {"agent_type": "file_reader", "intent": "read_file", "outcome": {"success": False}, "timestamp": 1000.0, "error": "Timeout"},
            {"agent_type": "http_fetch", "intent": "fetch_url", "outcome": {"success": True}, "timestamp": 1001.0, "error": "Timeout"},
        ]
        results = extract_strategies(episodes, min_occurrences=3)
        assert len(results) == 0


class TestExtractHighConfidence(unittest.TestCase):
    def test_extract_high_confidence_pattern(self) -> None:
        episodes = [
            {"agent_type": "file_reader", "intent": "read_file", "outcome": {"success": True, "confidence": 0.9}, "timestamp": 1000.0, "error": None},
            {"agent_type": "code_analyzer", "intent": "read_file", "outcome": {"success": True, "confidence": 0.85}, "timestamp": 1001.0, "error": None},
            {"agent_type": "file_reader", "intent": "read_file", "outcome": {"success": True, "confidence": 0.95}, "timestamp": 1002.0, "error": None},
        ]
        results = extract_strategies(episodes, min_occurrences=3)
        assert len(results) == 1
        s = results[0]
        assert s.strategy_type == StrategyType.PROMPT_TECHNIQUE
        assert "read_file" in s.description
        assert s.confidence >= 0.8

    def test_extract_high_confidence_low_avg(self) -> None:
        episodes = [
            {"agent_type": "a", "intent": "task", "outcome": {"success": True, "confidence": 0.3}, "timestamp": 1000.0, "error": None},
            {"agent_type": "b", "intent": "task", "outcome": {"success": True, "confidence": 0.5}, "timestamp": 1001.0, "error": None},
            {"agent_type": "c", "intent": "task", "outcome": {"success": True, "confidence": 0.7}, "timestamp": 1002.0, "error": None},
        ]
        # avg confidence = 0.5 < 0.8 → no strategy
        results = extract_strategies(episodes, min_occurrences=3)
        assert len(results) == 0


class TestExtractCoordination(unittest.TestCase):
    def test_extract_coordination_pattern(self) -> None:
        episodes = [
            {"agent_type": "a", "intent": "fetch_url", "outcome": {"success": True, "confidence": 0.9}, "timestamp": 1000.0, "error": None},
            {"agent_type": "b", "intent": "parse_html", "outcome": {"success": True, "confidence": 0.8}, "timestamp": 1010.0, "error": None},
            {"agent_type": "a", "intent": "fetch_url", "outcome": {"success": True, "confidence": 0.9}, "timestamp": 1100.0, "error": None},
            {"agent_type": "c", "intent": "parse_html", "outcome": {"success": True, "confidence": 0.8}, "timestamp": 1110.0, "error": None},
            {"agent_type": "a", "intent": "fetch_url", "outcome": {"success": True, "confidence": 0.9}, "timestamp": 1200.0, "error": None},
            {"agent_type": "b", "intent": "parse_html", "outcome": {"success": True, "confidence": 0.8}, "timestamp": 1210.0, "error": None},
        ]
        results = extract_strategies(episodes, min_occurrences=3)
        coord = [s for s in results if s.strategy_type == StrategyType.COORDINATION]
        assert len(coord) == 1
        assert "fetch_url" in coord[0].description
        assert "parse_html" in coord[0].description

    def test_extract_coordination_outside_window(self) -> None:
        episodes = [
            {"agent_type": "a", "intent": "fetch_url", "outcome": {"success": True, "confidence": 0.9}, "timestamp": 1000.0, "error": None},
            {"agent_type": "b", "intent": "parse_html", "outcome": {"success": True, "confidence": 0.8}, "timestamp": 1120.0, "error": None},
            {"agent_type": "a", "intent": "fetch_url", "outcome": {"success": True, "confidence": 0.9}, "timestamp": 2000.0, "error": None},
            {"agent_type": "b", "intent": "parse_html", "outcome": {"success": True, "confidence": 0.8}, "timestamp": 2120.0, "error": None},
            {"agent_type": "a", "intent": "fetch_url", "outcome": {"success": True, "confidence": 0.9}, "timestamp": 3000.0, "error": None},
            {"agent_type": "b", "intent": "parse_html", "outcome": {"success": True, "confidence": 0.8}, "timestamp": 3120.0, "error": None},
        ]
        # Pairs separated by 120s > 60s window → no coordination
        results = extract_strategies(episodes, min_occurrences=3)
        coord = [s for s in results if s.strategy_type == StrategyType.COORDINATION]
        assert len(coord) == 0


class TestExtractDedup(unittest.TestCase):
    def test_extract_dedup(self) -> None:
        """Same error across many agents — produces single strategy, not duplicates."""
        err = "Rate limit exceeded"
        episodes = [
            {"agent_type": "a", "intent": "fetch", "outcome": {"success": True, "confidence": 0.5}, "timestamp": 1000.0, "error": err},
            {"agent_type": "b", "intent": "fetch", "outcome": {"success": False, "confidence": 0.1}, "timestamp": 1001.0, "error": err},
            {"agent_type": "c", "intent": "query", "outcome": {"success": True, "confidence": 0.6}, "timestamp": 1002.0, "error": err},
            {"agent_type": "d", "intent": "query", "outcome": {"success": False, "confidence": 0.2}, "timestamp": 1003.0, "error": err},
        ]
        results = extract_strategies(episodes, min_occurrences=3)
        error_strategies = [s for s in results if s.strategy_type == StrategyType.ERROR_RECOVERY]
        assert len(error_strategies) == 1


class TestExtractEmpty(unittest.TestCase):
    def test_extract_empty_episodes(self) -> None:
        results = extract_strategies([], min_occurrences=3)
        assert results == []


class TestGetField(unittest.TestCase):
    def test_get_field_dict(self) -> None:
        d = {"agent_type": "file_reader", "intent": "read_file"}
        assert _get_field(d, "agent_type", "") == "file_reader"
        assert _get_field(d, "missing", "default") == "default"

    def test_get_field_object(self) -> None:
        class Obj:
            agent_type = "http_fetch"
            intent = "fetch"
        obj = Obj()
        assert _get_field(obj, "agent_type", "") == "http_fetch"
        assert _get_field(obj, "missing", "default") == "default"
