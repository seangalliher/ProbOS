"""Tests for StrategyAdvisor (AD-384)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from probos.cognitive.strategy_advisor import REL_STRATEGY, StrategyAdvisor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_strategy(tmp_path: Path, data: dict) -> None:
    """Write a strategy dict as a JSON file."""
    sid = data.get("id", "test")
    path = tmp_path / f"{sid}.json"
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_strategy(
    *,
    sid: str = "s1",
    description: str = "Recovery from: timeout",
    applicability: str = "When encountering: timeout",
    confidence: float = 0.7,
    strategy_type: str = "error_recovery",
    source_agents: list[str] | None = None,
    source_intent_types: list[str] | None = None,
) -> dict:
    return {
        "id": sid,
        "description": description,
        "applicability": applicability,
        "confidence": confidence,
        "strategy_type": strategy_type,
        "source_agents": source_agents or ["builder", "architect"],
        "source_intent_types": source_intent_types or ["diagnose_system"],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestQueryStrategies:
    def test_no_store(self) -> None:
        advisor = StrategyAdvisor(strategies_dir=None)
        result = advisor.query_strategies("diagnose_system", "builder")
        assert result == []

    def test_empty_results(self, tmp_path: Path) -> None:
        advisor = StrategyAdvisor(strategies_dir=tmp_path)
        result = advisor.query_strategies("diagnose_system", "builder")
        assert result == []

    def test_filters_low_confidence(self, tmp_path: Path) -> None:
        _write_strategy(tmp_path, _make_strategy(sid="low", confidence=0.1))
        advisor = StrategyAdvisor(strategies_dir=tmp_path)
        result = advisor.query_strategies("diagnose_system", "builder")
        assert len(result) == 0

    def test_sorts_by_relevance(self, tmp_path: Path) -> None:
        _write_strategy(tmp_path, _make_strategy(
            sid="s1", confidence=0.5,
            source_intent_types=["diagnose_system"],
        ))
        _write_strategy(tmp_path, _make_strategy(
            sid="s2", confidence=0.9,
            source_intent_types=["diagnose_system"],
        ))
        advisor = StrategyAdvisor(strategies_dir=tmp_path)
        result = advisor.query_strategies("diagnose_system", "builder")
        assert len(result) == 2
        # Higher confidence → higher relevance
        assert result[0]["id"] == "s2"
        assert result[1]["id"] == "s1"

    def test_max_results(self, tmp_path: Path) -> None:
        for i in range(5):
            _write_strategy(tmp_path, _make_strategy(
                sid=f"s{i}",
                confidence=0.6 + i * 0.05,
                source_intent_types=["diagnose_system"],
            ))
        advisor = StrategyAdvisor(strategies_dir=tmp_path)
        result = advisor.query_strategies("diagnose_system", "builder", max_results=3)
        assert len(result) == 3

    def test_hebbian_boost(self, tmp_path: Path) -> None:
        # s1 has lower confidence but high Hebbian weight
        _write_strategy(tmp_path, _make_strategy(
            sid="s1", confidence=0.5,
            source_intent_types=["diagnose_system"],
        ))
        # s2 has higher confidence but no Hebbian weight
        _write_strategy(tmp_path, _make_strategy(
            sid="s2", confidence=0.8,
            source_intent_types=["diagnose_system"],
        ))

        router = MagicMock()

        def fake_get_weight(source, target, rel_type=None):
            if source == "s1":
                return 0.9  # high Hebbian weight
            return 0.0  # no weight → advisor uses 0.5 default

        router.get_weight = MagicMock(side_effect=fake_get_weight)

        advisor = StrategyAdvisor(strategies_dir=tmp_path, hebbian_router=router)
        result = advisor.query_strategies("diagnose_system", "builder")

        # s1: relevance = 0.9 * 0.5 = 0.45
        # s2: relevance = 0.5 * 0.8 = 0.40 (default 0.5 Hebbian weight)
        assert result[0]["id"] == "s1"


class TestFormatForContext:
    def test_empty_strategies(self) -> None:
        advisor = StrategyAdvisor()
        assert advisor.format_for_context([]) == ""

    def test_formats_content(self) -> None:
        strategies = [
            _make_strategy(sid="s1", description="Recovery from: timeout"),
            _make_strategy(sid="s2", description="High-confidence approach"),
        ]
        advisor = StrategyAdvisor()
        text = advisor.format_for_context(strategies)
        assert "[CREW EXPERIENCE" in text
        assert "Recovery from: timeout" in text
        assert "High-confidence approach" in text
        assert "[END CREW EXPERIENCE]" in text
        assert "Confidence:" in text


class TestRecordOutcome:
    def test_success(self) -> None:
        router = MagicMock()
        advisor = StrategyAdvisor(hebbian_router=router)
        advisor.record_outcome("s1", "builder", success=True)
        router.record_interaction.assert_called_once_with(
            source="s1", target="builder", success=True, rel_type=REL_STRATEGY,
        )

    def test_no_router(self) -> None:
        advisor = StrategyAdvisor()
        # Should not raise
        advisor.record_outcome("s1", "builder", success=True)

    def test_no_strategy_id(self) -> None:
        router = MagicMock()
        advisor = StrategyAdvisor(hebbian_router=router)
        advisor.record_outcome("", "builder", success=True)
        router.record_interaction.assert_not_called()


class TestConstants:
    def test_rel_strategy_value(self) -> None:
        assert REL_STRATEGY == "strategy"
