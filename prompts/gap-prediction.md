# AD-385: Proactive Capability Gap Prediction

## Goal

Close the "system doesn't want anything" gap. Today, capability gaps are only detected when a user request fails to match any intent (`is_capability_gap()` regex or `dag.capability_gap` flag). The system never proactively says "Captain, I've noticed we struggle with X — shall I design a specialist?" This AD adds a dream pass that identifies recurring near-misses and proposes agent designs before the Captain hits the wall.

## Architecture

**Pattern:** New dream pass in `DreamEngine`, similar to AD-383 (Strategy Extraction). Runs after strategy extraction as step 6 of the full dream cycle. Output feeds into the existing self-mod pipeline via a callback.

## Reference Files (read these first)

- `src/probos/cognitive/dreaming.py` — `DreamEngine`, `DreamScheduler`, `DreamReport`, `dream_cycle()`
- `src/probos/cognitive/decomposer.py` — `is_capability_gap()` regex, `KNOWN_CAPABILITIES`
- `src/probos/cognitive/self_mod.py` — `handle_unhandled_intent()` entry point
- `src/probos/cognitive/strategy.py` — AD-383 strategy extraction (for pattern reference)

## Files to Create

### `src/probos/cognitive/gap_predictor.py` (~180 lines)

```python
"""AD-385: Proactive capability gap prediction from episodic patterns."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CapabilityGapPrediction:
    """A predicted capability gap identified from episodic patterns."""
    id: str  # descriptive key, e.g., "gap:sentiment_analysis"
    gap_description: str  # what capability is missing
    evidence_type: str  # "low_confidence" | "repeated_fallback" | "partial_coverage"
    evidence_summary: str  # human-readable evidence
    evidence_count: int  # number of supporting episodes
    suggested_intent: str  # proposed intent name
    suggested_description: str  # what the new agent should do
    affected_intent_types: list[str]  # existing intents that struggled
    priority: str = "medium"  # "low", "medium", "high"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "gap_description": self.gap_description,
            "evidence_type": self.evidence_type,
            "evidence_summary": self.evidence_summary,
            "evidence_count": self.evidence_count,
            "suggested_intent": self.suggested_intent,
            "suggested_description": self.suggested_description,
            "affected_intent_types": self.affected_intent_types,
            "priority": self.priority,
            "created_at": self.created_at,
        }


def predict_gaps(
    episodes: list,
    confidence_threshold: float = 0.4,
    fallback_min_count: int = 3,
    low_confidence_min_count: int = 5,
) -> list[CapabilityGapPrediction]:
    """Predict capability gaps from episodic memory patterns.

    Three detection methods:

    1. **Repeated low confidence**: Group successful episodes by intent type.
       When an intent type consistently has avg confidence < confidence_threshold
       across low_confidence_min_count+ episodes, predict a specialization gap.
       The existing agent handles it, but poorly.

    2. **Repeated fallback**: Count episodes where the LLM decomposer returned
       a generic/fallback response (no intent matched, or confidence < 0.2).
       Group by the original request topic. When a topic appears
       fallback_min_count+ times, predict a capability gap.

    3. **Partial DAG coverage**: Group episodes by their DAG structure.
       When a DAG has N nodes but one node consistently fails (>50% failure rate
       across 3+ attempts), predict a capability gap for that specific subtask.

    Each episode is expected to have (dict or object):
    - `agent_type` (str)
    - `intent` (str)
    - `outcome` (dict) with `success` (bool), `confidence` (float)
    - `timestamp` (float)
    - `error` (str | None)
    - `original_text` (str | None) — original user request (for fallback grouping)
    - `dag_node_id` (str | None) — which DAG node this was
    - `dag_id` (str | None) — parent DAG identifier

    Returns deduplicated list of CapabilityGapPrediction objects.
    """
    predictions: dict[str, CapabilityGapPrediction] = {}

    # Method 1: Repeated low confidence
    # Group by intent type, compute avg confidence for successful episodes
    intent_confidences: dict[str, list[float]] = {}
    for ep in episodes:
        outcome = _get_field(ep, 'outcome', {})
        success = outcome.get('success') if isinstance(outcome, dict) else getattr(outcome, 'success', False)
        if success:
            intent = _get_field(ep, 'intent', '')
            if intent:
                conf = outcome.get('confidence', 0.0) if isinstance(outcome, dict) else getattr(outcome, 'confidence', 0.0)
                intent_confidences.setdefault(intent, []).append(conf)

    for intent, confs in intent_confidences.items():
        if len(confs) < low_confidence_min_count:
            continue
        avg_conf = sum(confs) / len(confs)
        if avg_conf < confidence_threshold:
            pid = f"gap:low_conf:{intent}"
            predictions[pid] = CapabilityGapPrediction(
                id=pid,
                gap_description=f"Low confidence on {intent} (avg={avg_conf:.2f})",
                evidence_type="low_confidence",
                evidence_summary=f"{len(confs)} episodes with avg confidence {avg_conf:.2f}",
                evidence_count=len(confs),
                suggested_intent=f"{intent}_specialist",
                suggested_description=f"Specialized agent for {intent} to improve confidence from {avg_conf:.2f}",
                affected_intent_types=[intent],
                priority="high" if avg_conf < 0.2 else "medium",
            )

    # Method 2: Repeated fallback (no intent or very low confidence)
    # Group by first 3 significant words of original_text for topic clustering
    fallback_topics: dict[str, list] = {}
    for ep in episodes:
        outcome = _get_field(ep, 'outcome', {})
        conf = outcome.get('confidence', 0.0) if isinstance(outcome, dict) else getattr(outcome, 'confidence', 0.0)
        intent = _get_field(ep, 'intent', '')
        text = _get_field(ep, 'original_text', '') or ''
        # Consider it a fallback if no intent or very low confidence
        if (not intent or conf < 0.2) and text:
            # Simple topic extraction: first 3 non-stopword words
            topic = _extract_topic(text)
            if topic:
                fallback_topics.setdefault(topic, []).append(ep)

    for topic, group in fallback_topics.items():
        if len(group) < fallback_min_count:
            continue
        pid = f"gap:fallback:{topic}"
        predictions[pid] = CapabilityGapPrediction(
            id=pid,
            gap_description=f"Repeated fallback on topic: {topic}",
            evidence_type="repeated_fallback",
            evidence_summary=f"{len(group)} requests about '{topic}' fell back to generic handling",
            evidence_count=len(group),
            suggested_intent=f"handle_{topic.replace(' ', '_')}",
            suggested_description=f"Handle requests about {topic}",
            affected_intent_types=[],
            priority="high",
        )

    # Method 3: Partial DAG coverage
    # Group by dag_id, find nodes with >50% failure rate
    dag_nodes: dict[str, dict[str, list[bool]]] = {}  # dag_id -> {node_id -> [success, ...]}
    for ep in episodes:
        dag_id = _get_field(ep, 'dag_id', '') or ''
        node_id = _get_field(ep, 'dag_node_id', '') or ''
        if dag_id and node_id:
            outcome = _get_field(ep, 'outcome', {})
            success = outcome.get('success') if isinstance(outcome, dict) else getattr(outcome, 'success', False)
            dag_nodes.setdefault(dag_id, {}).setdefault(node_id, []).append(bool(success))

    # Aggregate across DAGs: if a node_id fails >50% across 3+ attempts
    node_failure_rates: dict[str, tuple[int, int]] = {}  # node_id -> (failures, total)
    for dag_id, nodes in dag_nodes.items():
        for node_id, results in nodes.items():
            if node_id not in node_failure_rates:
                node_failure_rates[node_id] = (0, 0)
            fails, total = node_failure_rates[node_id]
            node_failure_rates[node_id] = (fails + results.count(False), total + len(results))

    for node_id, (fails, total) in node_failure_rates.items():
        if total >= 3 and fails / total > 0.5:
            pid = f"gap:partial:{node_id}"
            predictions[pid] = CapabilityGapPrediction(
                id=pid,
                gap_description=f"DAG node '{node_id}' fails {fails}/{total} times",
                evidence_type="partial_coverage",
                evidence_summary=f"Node '{node_id}' has {fails/total*100:.0f}% failure rate across {total} attempts",
                evidence_count=total,
                suggested_intent=f"{node_id}_improved",
                suggested_description=f"More reliable handler for {node_id} subtask",
                affected_intent_types=[node_id],
                priority="high" if fails / total > 0.75 else "medium",
            )

    return list(predictions.values())


_STOP_WORDS = frozenset({"the", "a", "an", "is", "are", "was", "were", "be", "been",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "it", "this", "that",
    "i", "me", "my", "we", "you", "do", "does", "did", "can", "could", "will",
    "would", "should", "have", "has", "had", "what", "when", "where", "how", "why",
    "and", "or", "but", "not", "no", "so", "if"})


def _extract_topic(text: str) -> str:
    """Extract a simple topic key from text: first 3 non-stopword words, lowercased."""
    words = [w.lower().strip(".,!?;:'\"") for w in text.split()]
    significant = [w for w in words if w and w not in _STOP_WORDS]
    return " ".join(significant[:3])


def _get_field(obj, name: str, default: Any) -> Any:
    """Get a field from either a dict or an object."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
```

## Files to Modify

### `src/probos/cognitive/dreaming.py`

1. Add import: `from probos.cognitive.gap_predictor import predict_gaps, CapabilityGapPrediction`
2. Add `gaps_predicted: int = 0` field to `DreamReport`
3. In `DreamEngine.dream_cycle()`, after step 5 (strategy extraction from AD-383), add step 6:

```python
# Step 6: Capability gap prediction (AD-385)
gap_predictions = predict_gaps(episodes)
report.gaps_predicted = len(gap_predictions)
if gap_predictions and self._gap_prediction_fn:
    self._gap_prediction_fn(gap_predictions)
```

4. Add `_gap_prediction_fn: Callable | None = None` to `DreamEngine.__init__()` as parameter `gap_prediction_fn=None`
5. Pass through from `DreamScheduler.__init__()`

### `src/probos/runtime.py`

Wire the gap prediction callback to surface predictions via events:

```python
# In start(), where DreamScheduler is created:
gap_prediction_fn = self._on_gap_predictions

# Add method:
def _on_gap_predictions(self, predictions: list) -> None:
    """Broadcast gap predictions to HXI."""
    for p in predictions:
        self._emit_event({
            "type": "capability_gap_predicted",
            "data": p.to_dict(),
        })
    logger.info("Dream cycle predicted %d capability gaps", len(predictions))
```

## Tests

### Create `tests/test_gap_predictor.py` (~140 lines)

1. **`test_prediction_to_dict`** — Verify serialization
2. **`test_low_confidence_gap`** — 6 episodes with intent="analyze_code", avg confidence 0.3 → prediction with priority "medium"
3. **`test_low_confidence_very_low`** — avg confidence 0.15 → priority "high"
4. **`test_low_confidence_below_min_count`** — Only 3 episodes (min=5) → no prediction
5. **`test_low_confidence_high_avg`** — avg confidence 0.8 → no prediction
6. **`test_repeated_fallback`** — 4 episodes with no intent, similar text → fallback prediction
7. **`test_repeated_fallback_below_min`** — Only 2 episodes → no prediction
8. **`test_partial_dag_coverage`** — DAG node fails 4/5 times → partial coverage prediction
9. **`test_partial_dag_low_failure`** — Node fails 1/5 → no prediction (below 50%)
10. **`test_partial_dag_insufficient_attempts`** — Only 2 attempts → no prediction (need 3+)
11. **`test_extract_topic`** — "How do I analyze Python code?" → "analyze python code"
12. **`test_extract_topic_short`** — "help" → "help"
13. **`test_empty_episodes`** — Empty list → empty result
14. **`test_get_field_dict_and_object`** — Works with both types

## Constraints

- No LLM calls — purely programmatic pattern matching
- `DreamReport.gaps_predicted` defaults to 0 — backward compatible
- `gap_prediction_fn` defaults to None — no behavior change if not wired
- Do not modify the existing dream passes or AD-383 strategy extraction
- Episode format is flexible (dict or object) via `_get_field()`
