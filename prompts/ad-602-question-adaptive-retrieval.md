# AD-602: Question-Adaptive Retrieval Strategy Selection

**Status:** Ready for builder
**Scope:** New file + integration edits (~200 lines new, ~30 lines edits)
**Depends on:** AD-567b (salience-weighted recall), AD-430c (memory injection)

**Acceptance Criteria:**
- All 12 tests pass
- No new lint errors
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Summary

All recall queries use the same retrieval strategy regardless of question type. "What happened yesterday?" (temporal) and "Why did the trust drop?" (causal) use identical `recall_weighted()` parameters. This wastes recall budget on low-relevance results and misses high-relevance results that require different weight profiles.

This AD adds a keyword-based question classifier and a retrieval strategy selector. The classifier categorizes queries into four types (TEMPORAL, CAUSAL, SOCIAL, FACTUAL), and the selector maps each type to an optimal retrieval strategy with tuned recall parameters.

Key capabilities:
1. `QuestionClassifier` — classify queries via keyword matching (no LLM).
2. `RetrievalStrategySelector` — map question types to optimized recall strategies.
3. `CognitiveAgent` integration — classify the query before recall, apply the selected strategy.

## Architecture

```
CognitiveAgent._recall_relevant_memories(intent, observation)
    │
    ├── Build query string from intent
    │
    ▼
QuestionClassifier.classify(query)
    ├── keyword scan → QuestionType (TEMPORAL | CAUSAL | SOCIAL | FACTUAL)
    │
    ▼
RetrievalStrategySelector.select_strategy(question_type)
    ├── TEMPORAL → anchor recall, boost recency_weight=0.30
    ├── CAUSAL  → weighted recall, k=10, boost semantic=0.45
    ├── SOCIAL  → anchor recall, filter by trigger_agent/department
    └── FACTUAL → standard weighted recall (default weights)
    │
    ▼
Apply strategy to EpisodicMemory recall call
```

---

## File Changes

| File | Change |
|------|--------|
| `src/probos/cognitive/question_classifier.py` | **NEW** — QuestionClassifier, RetrievalStrategySelector, QuestionType enum, RetrievalStrategy dataclass |
| `src/probos/config.py` | Add QuestionAdaptiveConfig + wire into SystemConfig |
| `src/probos/cognitive/cognitive_agent.py` | Classify query in `_recall_relevant_memories()`, apply strategy |
| `tests/test_ad602_question_adaptive.py` | **NEW** — 12 tests |

---

## Implementation

### Section 1: QuestionAdaptiveConfig

**File:** `src/probos/config.py`

Add a new Pydantic config model. Place it after `ExpertiseConfig` (or after `ConsultationConfig` if AD-600 is not yet built):

```python
class QuestionAdaptiveConfig(BaseModel):
    """AD-602: Question-adaptive retrieval strategy configuration."""

    enabled: bool = True
    strategy_overrides: dict[str, dict] = {}  # per-type weight overrides, e.g. {"TEMPORAL": {"recency_weight": 0.35}}
```

Wire into `SystemConfig` (after the last config field):

```python
    question_adaptive: QuestionAdaptiveConfig = QuestionAdaptiveConfig()  # AD-602
```

### Section 2: QuestionClassifier and RetrievalStrategySelector

**File:** `src/probos/cognitive/question_classifier.py` (NEW)

```python
"""AD-602: Question-Adaptive Retrieval Strategy Selection.

Keyword-based question classifier and retrieval strategy selector.
Classifies queries into four types and maps each to an optimized
recall strategy with tuned parameters.

No LLM dependency — classification is deterministic keyword matching.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class QuestionType(str, Enum):
    """Classification of query intent for retrieval optimization."""

    TEMPORAL = "temporal"  # When-oriented: "what happened yesterday?"
    CAUSAL = "causal"      # Why-oriented: "why did the trust drop?"
    SOCIAL = "social"      # Who-oriented: "which agent reported this?"
    FACTUAL = "factual"    # What-oriented: "what is the current status?"


@dataclass
class RetrievalStrategy:
    """Optimized retrieval parameters for a question type."""

    recall_method: str = "weighted"  # "weighted", "anchor", "anchor_scored"
    k: int = 5
    context_budget: int = 1500  # max tokens of memory context
    anchor_filters: dict[str, Any] = field(default_factory=dict)
    weights_override: dict[str, float] | None = None


# Keyword lists for classification
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
    "who", "whom", "which agent", "department", "crew",
    "reported", "said", "told", "asked", "mentioned",
    "team", "officer", "chief", "captain",
}


class QuestionClassifier:
    """Classify queries into QuestionType via keyword matching.

    Classification priority: TEMPORAL > CAUSAL > SOCIAL > FACTUAL.
    If multiple types match, the highest-priority match wins.
    Ambiguous queries default to FACTUAL.
    """

    def classify(self, query: str) -> QuestionType:
        """Classify a query string into a QuestionType.

        Parameters
        ----------
        query : str
            The query to classify.

        Returns
        -------
        QuestionType
            The classified question type. Defaults to FACTUAL.
        """
        if not query:
            return QuestionType.FACTUAL

        query_lower = query.lower()
        words = set(query_lower.split())

        # Check each type in priority order
        if words & _TEMPORAL_KEYWORDS:
            return QuestionType.TEMPORAL
        if words & _CAUSAL_KEYWORDS:
            return QuestionType.CAUSAL
        # Social needs phrase matching too
        if words & {"who", "whom"} or "which agent" in query_lower or "department" in query_lower:
            return QuestionType.SOCIAL

        return QuestionType.FACTUAL


# Default strategies per question type
_DEFAULT_STRATEGIES: dict[QuestionType, RetrievalStrategy] = {
    QuestionType.TEMPORAL: RetrievalStrategy(
        recall_method="anchor_scored",
        k=5,
        context_budget=1500,
        anchor_filters={},  # time_range set dynamically by caller
        weights_override={"recency_weight": 0.30, "semantic_weight": 0.25},
    ),
    QuestionType.CAUSAL: RetrievalStrategy(
        recall_method="weighted",
        k=10,
        context_budget=2000,
        weights_override={"semantic_weight": 0.45, "recency_weight": 0.10},
    ),
    QuestionType.SOCIAL: RetrievalStrategy(
        recall_method="anchor_scored",
        k=5,
        context_budget=1500,
        anchor_filters={},  # trigger_agent/department set dynamically
        weights_override=None,
    ),
    QuestionType.FACTUAL: RetrievalStrategy(
        recall_method="weighted",
        k=5,
        context_budget=1500,
        weights_override=None,  # use defaults
    ),
}


class RetrievalStrategySelector:
    """Map QuestionType to an optimized RetrievalStrategy.

    Parameters
    ----------
    config : QuestionAdaptiveConfig-like or None
        Configuration with optional per-type weight overrides.
    """

    def __init__(self, config: Any = None) -> None:
        self._overrides: dict[str, dict] = {}
        if config is not None:
            self._overrides = getattr(config, "strategy_overrides", {})

    def select_strategy(self, question_type: QuestionType) -> RetrievalStrategy:
        """Select the optimal retrieval strategy for a question type.

        Parameters
        ----------
        question_type : QuestionType
            The classified question type.

        Returns
        -------
        RetrievalStrategy
            The strategy with optimized recall parameters.
        """
        strategy = _DEFAULT_STRATEGIES.get(question_type, _DEFAULT_STRATEGIES[QuestionType.FACTUAL])

        # Apply per-type overrides from config
        type_key = question_type.value.upper()
        if type_key in self._overrides:
            override = self._overrides[type_key]
            if "k" in override:
                strategy = RetrievalStrategy(
                    recall_method=strategy.recall_method,
                    k=override["k"],
                    context_budget=strategy.context_budget,
                    anchor_filters=strategy.anchor_filters,
                    weights_override={
                        **(strategy.weights_override or {}),
                        **override.get("weights", {}),
                    } if strategy.weights_override or override.get("weights") else None,
                )
            elif "weights" in override:
                existing = dict(strategy.weights_override or {})
                existing.update(override["weights"])
                strategy = RetrievalStrategy(
                    recall_method=strategy.recall_method,
                    k=strategy.k,
                    context_budget=strategy.context_budget,
                    anchor_filters=strategy.anchor_filters,
                    weights_override=existing,
                )

        return strategy
```

### Section 3: CognitiveAgent Integration

**File:** `src/probos/cognitive/cognitive_agent.py`

#### 3a: Instance variables

In `__init__`, after the `self._consultation_protocol` line (added by AD-594), add:

```python
        # AD-602: Question-adaptive retrieval
        self._question_classifier: Any = None
        self._retrieval_strategy_selector: Any = None
```

#### 3b: Lazy initialization in _recall_relevant_memories

At the start of `_recall_relevant_memories()`, after the existing guard checks and before the `try:` block, add lazy initialization of the classifier and selector:

```python
        # AD-602: Lazy-init question classifier
        if self._question_classifier is None:
            try:
                from probos.cognitive.question_classifier import (
                    QuestionClassifier,
                    RetrievalStrategySelector,
                )
                _qa_config = None
                if hasattr(self._runtime, 'config') and hasattr(self._runtime.config, 'question_adaptive'):
                    _qa_config = self._runtime.config.question_adaptive
                    if not _qa_config.enabled:
                        self._question_classifier = False  # sentinel: disabled
                if self._question_classifier is None:
                    self._question_classifier = QuestionClassifier()
                    self._retrieval_strategy_selector = RetrievalStrategySelector(config=_qa_config)
            except Exception:
                self._question_classifier = False  # sentinel: unavailable
                logger.debug("AD-602: Question classifier unavailable", exc_info=True)
```

#### 3c: Apply classification

Inside the `try:` block of `_recall_relevant_memories()`, after the query string is built but before the recall call, add:

```python
            # AD-602: Classify query and select strategy
            _question_type = None
            _strategy = None
            if self._question_classifier and self._question_classifier is not False:
                try:
                    _question_type = self._question_classifier.classify(query)
                    _strategy = self._retrieval_strategy_selector.select_strategy(_question_type)
                    logger.debug(
                        "AD-602: Query classified as %s — strategy: method=%s, k=%d",
                        _question_type.value, _strategy.recall_method, _strategy.k,
                    )
                except Exception:
                    logger.debug("AD-602: Classification failed, using default recall", exc_info=True)
```

**Builder:** The strategy is now available for use in the recall call. However, integrating the strategy into the actual recall call parameters is complex and depends on the existing recall flow. For this AD, **only** apply the `k` parameter and `weights_override` to `recall_weighted()` if the strategy specifies them. Do NOT refactor the existing recall flow. The minimal integration is:

- If `_strategy` is not None and `_strategy.recall_method == "weighted"`:
  - Pass `_strategy.k` as the `k` parameter to `recall_weighted()`
- If `_strategy.weights_override` is not None:
  - Store in observation under key `"_ad602_weights_override"` for future use by the recall weighting logic

This is a minimal first integration. Full strategy application (switching between recall methods based on type) is deferred to AD-604 (Spreading Activation).

---

## Tests

**File:** `tests/test_ad602_question_adaptive.py` (NEW)

### Test List

| # | Test Name | What It Verifies |
|---|-----------|------------------|
| 1 | `test_classify_temporal` | "When did the trust update happen?" → TEMPORAL |
| 2 | `test_classify_causal` | "Why did the trust score drop?" → CAUSAL |
| 3 | `test_classify_social` | "Who reported the anomaly?" → SOCIAL |
| 4 | `test_classify_factual` | "What is the current system status?" → FACTUAL |
| 5 | `test_classify_ambiguous_defaults_factual` | "Hello how are you" → FACTUAL |
| 6 | `test_classify_empty_string` | "" → FACTUAL |
| 7 | `test_strategy_temporal` | TEMPORAL → anchor_scored, recency_weight=0.30 |
| 8 | `test_strategy_causal` | CAUSAL → weighted, k=10, semantic=0.45 |
| 9 | `test_strategy_social` | SOCIAL → anchor_scored |
| 10 | `test_strategy_factual` | FACTUAL → weighted, k=5, default weights |
| 11 | `test_config_disabled_uses_default` | When enabled=False, classifier is not used |
| 12 | `test_strategy_override_from_config` | Config override changes strategy parameters |

### Test Stubs

```python
import pytest

from probos.cognitive.question_classifier import (
    QuestionClassifier,
    QuestionType,
    RetrievalStrategy,
    RetrievalStrategySelector,
)


@pytest.fixture
def classifier():
    return QuestionClassifier()


@pytest.fixture
def selector():
    return RetrievalStrategySelector()
```

---

## Targeted Test Commands

After Section 1 (Config):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad602_question_adaptive.py -v -k "config"
```

After Section 2 (Classifier + Selector):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad602_question_adaptive.py -v
```

After Section 3 (CognitiveAgent integration):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad602_question_adaptive.py -v
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_cognitive_agent.py -v -x
```

Full suite (after all sections complete):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

After all tests pass:

- **PROGRESS.md:** Add line `AD-602 Question-Adaptive Retrieval — CLOSED`
- **docs/development/roadmap.md:** Update the AD-602 row status to `Complete`
- **DECISIONS.md:** Add entry:
  ```
  AD-602: Question-Adaptive Retrieval. Keyword-based QuestionClassifier maps
  queries to TEMPORAL/CAUSAL/SOCIAL/FACTUAL types. RetrievalStrategySelector
  maps each type to optimized recall parameters (k, weights, method). Minimal
  CognitiveAgent integration applies k and weight overrides. No LLM dependency.
  Unlocks AD-604 (Spreading Activation for CAUSAL queries).
  ```

---

## Scope Boundaries

**DO:**
- Create `question_classifier.py` with QuestionClassifier, RetrievalStrategySelector, QuestionType, RetrievalStrategy.
- Add QuestionAdaptiveConfig to config.py and wire into SystemConfig.
- Add lazy-init classifier/selector in CognitiveAgent._recall_relevant_memories().
- Apply minimal strategy parameters (k, weights) to recall call.
- Write all 12 tests.

**DO NOT:**
- Use LLM-based question classification (keyword matching only).
- Add DEEP/ORACLE tier escalation.
- Build multi-strategy fusion.
- Refactor the existing recall flow in CognitiveAgent.
- Switch between recall methods based on strategy (deferred to AD-604).
- Modify existing tests.
- Add API endpoints or HXI dashboard panels.
