"""AD-602: Question-Adaptive Retrieval Strategy Selection.

Keyword-based question classifier and retrieval strategy selector.
Classifies queries into four types and maps each to optimized recall
parameters. Classification is deterministic and has no LLM dependency.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class QuestionType(StrEnum):
    """Classification of query intent for retrieval optimization."""

    TEMPORAL = "temporal"
    CAUSAL = "causal"
    SOCIAL = "social"
    FACTUAL = "factual"


@dataclass
class RetrievalStrategy:
    """Optimized retrieval parameters for a question type."""

    recall_method: str = "weighted"
    k: int = 5
    context_budget: int = 1500
    anchor_filters: dict[str, Any] = field(default_factory=dict)
    weights_override: dict[str, float] | None = None


_TEMPORAL_KEYWORDS: set[str] = {
    "when", "yesterday", "today", "last", "recently", "before",
    "after", "earlier", "ago", "previous", "latest", "during",
    "watch", "morning", "evening", "night", "hour", "minute",
    "cycle", "shift", "time",
}

_CAUSAL_KEYWORDS: set[str] = {
    "why", "because", "caused", "cause", "reason", "led",
    "resulted", "consequence", "due", "effect", "explain",
    "root", "trigger", "origin", "source", "fault",
}

_SOCIAL_KEYWORDS: set[str] = {
    "who", "whom", "department", "crew", "reported", "said", "told",
    "asked", "mentioned", "team", "officer", "chief", "captain",
}


class QuestionClassifier:
    """Classify queries into QuestionType via keyword matching."""

    def classify(self, query: str) -> QuestionType:
        """Classify a query string into a QuestionType."""
        if not query:
            return QuestionType.FACTUAL

        query_lower = query.lower()
        words = set(re.findall(r"[a-z]+", query_lower))

        if words & _TEMPORAL_KEYWORDS:
            return QuestionType.TEMPORAL
        if words & _CAUSAL_KEYWORDS:
            return QuestionType.CAUSAL
        if words & _SOCIAL_KEYWORDS or "which agent" in query_lower:
            return QuestionType.SOCIAL

        return QuestionType.FACTUAL


_DEFAULT_STRATEGIES: dict[QuestionType, RetrievalStrategy] = {
    QuestionType.TEMPORAL: RetrievalStrategy(
        recall_method="anchor_scored",
        k=5,
        context_budget=1500,
        anchor_filters={},
        weights_override={
            "recency_weight": 0.30,
            "semantic_weight": 0.25,
            "recency": 0.30,
            "semantic": 0.25,
        },
    ),
    QuestionType.CAUSAL: RetrievalStrategy(
        recall_method="weighted",
        k=10,
        context_budget=2000,
        weights_override={
            "semantic_weight": 0.45,
            "recency_weight": 0.10,
            "semantic": 0.45,
            "recency": 0.10,
        },
    ),
    QuestionType.SOCIAL: RetrievalStrategy(
        recall_method="anchor_scored",
        k=5,
        context_budget=1500,
        anchor_filters={},
        weights_override=None,
    ),
    QuestionType.FACTUAL: RetrievalStrategy(
        recall_method="weighted",
        k=5,
        context_budget=1500,
        weights_override=None,
    ),
}


class RetrievalStrategySelector:
    """Map QuestionType to an optimized RetrievalStrategy."""

    def __init__(self, config: Any = None) -> None:
        self._overrides: dict[str, dict] = {}
        if config is not None and getattr(config, "enabled", True):
            self._overrides = dict(getattr(config, "strategy_overrides", {}) or {})

    def select_strategy(self, question_type: QuestionType) -> RetrievalStrategy:
        """Select the optimal retrieval strategy for a question type."""
        base = _DEFAULT_STRATEGIES.get(question_type, _DEFAULT_STRATEGIES[QuestionType.FACTUAL])
        strategy = replace(
            base,
            anchor_filters=dict(base.anchor_filters),
            weights_override=dict(base.weights_override) if base.weights_override else None,
        )

        type_key = question_type.value.upper()
        override = self._overrides.get(type_key)
        if not override:
            return strategy

        weights = override.get("weights", {})
        direct_weights = {
            key: value
            for key, value in override.items()
            if key.endswith("_weight") or key in {"semantic", "keyword", "trust", "hebbian", "recency", "anchor"}
        }
        merged_weights = dict(strategy.weights_override or {})
        merged_weights.update(direct_weights)
        merged_weights.update(weights)

        return RetrievalStrategy(
            recall_method=override.get("recall_method", strategy.recall_method),
            k=int(override.get("k", strategy.k)),
            context_budget=int(override.get("context_budget", strategy.context_budget)),
            anchor_filters=dict(override.get("anchor_filters", strategy.anchor_filters)),
            weights_override=merged_weights or None,
        )