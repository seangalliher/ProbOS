"""AD-385: Proactive capability gap prediction from episodic patterns."""

from __future__ import annotations

import time
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

    2. **Repeated fallback**: Count episodes where no intent matched or
       confidence < 0.2.  Group by the original request topic.  When a topic
       appears fallback_min_count+ times, predict a capability gap.

    3. **Partial DAG coverage**: Group episodes by their DAG structure.
       When a DAG node consistently fails (>50% failure rate across 3+
       attempts), predict a capability gap for that specific subtask.

    Returns deduplicated list of CapabilityGapPrediction objects.
    """
    predictions: dict[str, CapabilityGapPrediction] = {}

    # Method 1: Repeated low confidence
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
    fallback_topics: dict[str, list] = {}
    for ep in episodes:
        outcome = _get_field(ep, 'outcome', {})
        conf = outcome.get('confidence', 0.0) if isinstance(outcome, dict) else getattr(outcome, 'confidence', 0.0)
        intent = _get_field(ep, 'intent', '')
        text = _get_field(ep, 'original_text', '') or ''
        # Consider it a fallback if no intent or very low confidence
        if (not intent or conf < 0.2) and text:
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


def _get_field(obj: Any, name: str, default: Any) -> Any:
    """Get a field from either a dict or an object."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
