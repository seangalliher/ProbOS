"""AD-602: Tests for question-adaptive retrieval strategy selection."""

from __future__ import annotations

import pytest

from probos.cognitive.question_classifier import (
    QuestionClassifier,
    QuestionType,
    RetrievalStrategySelector,
)
from probos.config import QuestionAdaptiveConfig


@pytest.fixture
def classifier() -> QuestionClassifier:
    return QuestionClassifier()


@pytest.fixture
def selector() -> RetrievalStrategySelector:
    return RetrievalStrategySelector()


def test_classify_temporal(classifier: QuestionClassifier) -> None:
    assert classifier.classify("When did the trust update happen?") == QuestionType.TEMPORAL


def test_classify_causal(classifier: QuestionClassifier) -> None:
    assert classifier.classify("Why did the trust score drop?") == QuestionType.CAUSAL


def test_classify_social(classifier: QuestionClassifier) -> None:
    assert classifier.classify("Who reported the anomaly?") == QuestionType.SOCIAL


def test_classify_factual(classifier: QuestionClassifier) -> None:
    assert classifier.classify("What is the current system status?") == QuestionType.FACTUAL


def test_classify_ambiguous_defaults_factual(classifier: QuestionClassifier) -> None:
    assert classifier.classify("Hello how are you") == QuestionType.FACTUAL


def test_classify_empty_string(classifier: QuestionClassifier) -> None:
    assert classifier.classify("") == QuestionType.FACTUAL


def test_strategy_temporal(selector: RetrievalStrategySelector) -> None:
    strategy = selector.select_strategy(QuestionType.TEMPORAL)

    assert strategy.recall_method == "anchor_scored"
    assert strategy.weights_override is not None
    assert strategy.weights_override["recency_weight"] == 0.30


def test_strategy_causal(selector: RetrievalStrategySelector) -> None:
    strategy = selector.select_strategy(QuestionType.CAUSAL)

    assert strategy.recall_method == "weighted"
    assert strategy.k == 10
    assert strategy.weights_override is not None
    assert strategy.weights_override["semantic_weight"] == 0.45


def test_strategy_social(selector: RetrievalStrategySelector) -> None:
    strategy = selector.select_strategy(QuestionType.SOCIAL)

    assert strategy.recall_method == "anchor_scored"


def test_strategy_factual(selector: RetrievalStrategySelector) -> None:
    strategy = selector.select_strategy(QuestionType.FACTUAL)

    assert strategy.recall_method == "weighted"
    assert strategy.k == 5
    assert strategy.weights_override is None


def test_config_disabled_uses_default() -> None:
    config = QuestionAdaptiveConfig(
        enabled=False,
        strategy_overrides={"CAUSAL": {"k": 99, "weights": {"semantic_weight": 0.99}}},
    )
    selector = RetrievalStrategySelector(config=config)

    strategy = selector.select_strategy(QuestionType.CAUSAL)

    assert strategy.k == 10
    assert strategy.weights_override is not None
    assert strategy.weights_override["semantic_weight"] == 0.45


def test_strategy_override_from_config() -> None:
    config = QuestionAdaptiveConfig(
        strategy_overrides={
            "CAUSAL": {
                "k": 12,
                "weights": {"semantic_weight": 0.50, "semantic": 0.50},
            }
        }
    )
    selector = RetrievalStrategySelector(config=config)

    strategy = selector.select_strategy(QuestionType.CAUSAL)

    assert strategy.k == 12
    assert strategy.weights_override is not None
    assert strategy.weights_override["semantic_weight"] == 0.50
    assert strategy.weights_override["semantic"] == 0.50