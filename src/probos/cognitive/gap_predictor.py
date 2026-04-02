"""AD-385 / AD-539: Proactive capability gap prediction from episodic patterns."""

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


# ──────────────────────────────────────────────────────────────────────
# AD-539: Gap → Qualification Pipeline
# ──────────────────────────────────────────────────────────────────────

@dataclass
class GapReport:
    """A classified knowledge gap linked to skill framework and qualification paths."""

    id: str                             # e.g. "gap:agent_type:intent_type:timestamp_hex"
    agent_id: str                       # which agent has the gap
    agent_type: str                     # agent type for skill mapping
    gap_type: str                       # "knowledge" | "capability" | "data"
    description: str                    # human-readable gap description
    evidence_sources: list[str] = field(default_factory=list)
    affected_intent_types: list[str] = field(default_factory=list)
    failure_rate: float = 0.0           # aggregate failure rate across evidence
    episode_count: int = 0              # total supporting episodes
    mapped_skill_id: str = ""           # Skill Framework skill_id (if mappable)
    current_proficiency: int = 0        # agent's current proficiency level
    target_proficiency: int = 0         # target proficiency for gap closure
    qualification_path_id: str = ""     # qualification path triggered (if any)
    priority: str = "medium"            # "low" | "medium" | "high" | "critical"
    created_at: float = field(default_factory=time.time)
    resolved: bool = False
    resolved_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "gap_type": self.gap_type,
            "description": self.description,
            "evidence_sources": self.evidence_sources,
            "affected_intent_types": self.affected_intent_types,
            "failure_rate": self.failure_rate,
            "episode_count": self.episode_count,
            "mapped_skill_id": self.mapped_skill_id,
            "current_proficiency": self.current_proficiency,
            "target_proficiency": self.target_proficiency,
            "qualification_path_id": self.qualification_path_id,
            "priority": self.priority,
            "created_at": self.created_at,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at,
        }


def classify_gap(
    evidence_type: str,
    failure_rate: float,
    episode_count: int,
) -> str:
    """Classify a gap as knowledge, capability, or data.

    - knowledge: agent doesn't know how (training helps)
    - capability: agent fundamentally can't do this (escalation needed)
    - data: agent lacks information (information routing problem)
    """
    if evidence_type == "repeated_fallback":
        return "data"
    if failure_rate > 0.80 and episode_count >= 10:
        return "capability"
    return "knowledge"


def _priority_from_failure_rate(failure_rate: float) -> str:
    """Assign priority based on failure rate."""
    if failure_rate >= 0.80:
        return "critical"
    if failure_rate >= 0.60:
        return "high"
    if failure_rate >= 0.40:
        return "medium"
    return "low"


def detect_gaps(
    episodes: list,
    clusters: list,
    procedure_decay_results: list[dict],
    procedure_health_results: list[dict],
    agent_id: str = "",
    agent_type: str = "",
) -> list[GapReport]:
    """AD-539: Multi-source gap detection aggregating 4 evidence types.

    Sources:
    1. Existing predict_gaps() episode analysis
    2. Failure-dominant clusters (AD-531)
    3. Procedure decay (AD-538)
    4. Procedure health diagnosis (quality metrics)
    """
    from probos.config import (
        GAP_MIN_EPISODES,
        GAP_MIN_FAILURE_RATE,
        GAP_REPORT_MAX_PER_DREAM,
    )

    # Collect gaps keyed by intent-type tuple for deduplication
    gap_by_intents: dict[str, GapReport] = {}
    all_gaps: list[GapReport] = []

    def _intent_key(intents: list[str]) -> str:
        return "|".join(sorted(intents)) if intents else "__no_intent__"

    def _merge_or_add(gap: GapReport) -> None:
        key = _intent_key(gap.affected_intent_types)
        if key in gap_by_intents:
            existing = gap_by_intents[key]
            existing.evidence_sources.extend(gap.evidence_sources)
            existing.failure_rate = max(existing.failure_rate, gap.failure_rate)
            existing.episode_count += gap.episode_count
            # Keep higher priority
            priorities = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            if priorities.get(gap.priority, 0) > priorities.get(existing.priority, 0):
                existing.priority = gap.priority
        else:
            gap_by_intents[key] = gap
            all_gaps.append(gap)

    # Source 1: Existing predict_gaps()
    predictions = predict_gaps(episodes)
    for pred in predictions:
        gap_type = classify_gap(pred.evidence_type, 0.0, pred.evidence_count)
        ts_hex = hex(int(time.time() * 1000))[-6:]
        gap = GapReport(
            id=f"gap:{agent_type}:{pred.id}:{ts_hex}",
            agent_id=agent_id,
            agent_type=agent_type,
            gap_type=gap_type,
            description=pred.gap_description,
            evidence_sources=[f"episode:{pred.evidence_type}"],
            affected_intent_types=pred.affected_intent_types,
            failure_rate=0.0,
            episode_count=pred.evidence_count,
            priority=pred.priority,
        )
        _merge_or_add(gap)

    # Source 2: Failure-dominant clusters (AD-531)
    for cluster in clusters:
        is_failure = getattr(cluster, "is_failure_dominant", False)
        ep_count = getattr(cluster, "episode_count", 0)
        if not is_failure or ep_count < GAP_MIN_EPISODES:
            continue
        success_rate = getattr(cluster, "success_rate", 1.0)
        failure_rate = 1.0 - success_rate
        if failure_rate < GAP_MIN_FAILURE_RATE:
            continue
        cluster_id = getattr(cluster, "cluster_id", "unknown")
        intents = getattr(cluster, "intent_types", [])
        gap_type = classify_gap("failure_cluster", failure_rate, ep_count)
        ts_hex = hex(int(time.time() * 1000))[-6:]
        gap = GapReport(
            id=f"gap:{agent_type}:cluster:{cluster_id}:{ts_hex}",
            agent_id=agent_id,
            agent_type=agent_type,
            gap_type=gap_type,
            description=f"Failure-dominant cluster ({failure_rate:.0%} failure rate, {ep_count} episodes)",
            evidence_sources=[f"failure_cluster:{cluster_id}"],
            affected_intent_types=list(intents),
            failure_rate=failure_rate,
            episode_count=ep_count,
            priority=_priority_from_failure_rate(failure_rate),
        )
        _merge_or_add(gap)

    # Source 3: Procedure decay (AD-538)
    for decay in procedure_decay_results:
        proc_id = decay.get("id", "")
        proc_name = decay.get("name", proc_id)
        ts_hex = hex(int(time.time() * 1000))[-6:]
        gap = GapReport(
            id=f"gap:{agent_type}:decay:{proc_id}:{ts_hex}",
            agent_id=agent_id,
            agent_type=agent_type,
            gap_type="knowledge",
            description=f"Procedure '{proc_name}' decayed due to disuse",
            evidence_sources=[f"procedure_decay:{proc_id}"],
            affected_intent_types=decay.get("intent_types", []),
            failure_rate=0.0,
            episode_count=0,
            priority="low",
        )
        _merge_or_add(gap)

    # Source 4: Procedure health diagnosis
    for health in procedure_health_results:
        proc_id = health.get("id", "")
        proc_name = health.get("name", proc_id)
        diagnosis = health.get("diagnosis", "")
        if not diagnosis:
            continue
        is_fix = diagnosis.startswith("FIX:")
        priority = "medium" if is_fix else "low"
        ts_hex = hex(int(time.time() * 1000))[-6:]
        gap = GapReport(
            id=f"gap:{agent_type}:health:{proc_id}:{ts_hex}",
            agent_id=agent_id,
            agent_type=agent_type,
            gap_type="knowledge",
            description=f"Procedure '{proc_name}' health: {diagnosis}",
            evidence_sources=[f"procedure_health:{diagnosis}:{proc_id}"],
            affected_intent_types=health.get("intent_types", []),
            failure_rate=health.get("failure_rate", 0.0),
            episode_count=health.get("total_selections", 0),
            priority=priority,
        )
        _merge_or_add(gap)

    # Cap output
    result = all_gaps[:GAP_REPORT_MAX_PER_DREAM]
    return result


# ── Skill Framework Bridge (AD-539 Part 3) ──────────────────────────

def _intent_to_skill_id(
    intent_types: list[str],
    registered_skills: list | None = None,
) -> str:
    """Map intent types to the best-matching Skill Framework skill_id.

    1. Exact match against registered skill IDs
    2. Falls back to 'duty_execution' PCC
    """
    if registered_skills:
        skill_ids = set()
        for s in registered_skills:
            sid = getattr(s, "skill_id", None) or (s.get("skill_id") if isinstance(s, dict) else "")
            if sid:
                skill_ids.add(sid)
        for intent in intent_types:
            if intent in skill_ids:
                return intent
    return "duty_execution"


async def map_gap_to_skill(
    gap: GapReport,
    skill_service: Any,
) -> GapReport:
    """Map a gap's intent types to a Skill Framework skill and check proficiency."""
    from probos.config import GAP_PROFICIENCY_TARGET

    if not skill_service:
        return gap

    try:
        # Get registered skills from the registry
        registry = getattr(skill_service, "registry", None)
        registered = None
        if registry:
            registered = list(getattr(registry, "_skills", {}).values())

        gap.mapped_skill_id = _intent_to_skill_id(
            gap.affected_intent_types, registered
        )

        # Check current proficiency
        profile = await skill_service.get_profile(gap.agent_id)
        if profile:
            all_skills = list(
                getattr(profile, "pccs", [])
                + getattr(profile, "role_skills", [])
                + getattr(profile, "acquired_skills", [])
            )
            for sr in all_skills:
                sid = getattr(sr, "skill_id", "")
                if sid == gap.mapped_skill_id:
                    gap.current_proficiency = getattr(sr, "proficiency", 0)
                    if isinstance(gap.current_proficiency, int):
                        break
                    # ProficiencyLevel enum → int
                    gap.current_proficiency = int(gap.current_proficiency)
                    break

        gap.target_proficiency = GAP_PROFICIENCY_TARGET
    except Exception:
        pass

    return gap


# ── Qualification Path Triggering (AD-539 Part 4) ───────────────────

async def trigger_qualification_if_needed(
    gap: GapReport,
    skill_service: Any,
) -> GapReport:
    """If the gap reveals proficiency below target, start a qualification path."""
    if not skill_service:
        return gap
    if not gap.mapped_skill_id:
        return gap
    if gap.current_proficiency >= gap.target_proficiency:
        return gap
    if gap.gap_type in ("capability", "data"):
        return gap

    try:
        # Determine path ID from agent context
        path_id = f"gap_qualification:{gap.mapped_skill_id}"

        # Check if a qualification path already exists
        existing = await skill_service.get_qualification_record(
            gap.agent_id, path_id
        )
        if existing:
            gap.qualification_path_id = path_id
            return gap

        # Start new qualification
        await skill_service.start_qualification(gap.agent_id, path_id)
        gap.qualification_path_id = path_id
    except Exception:
        pass

    return gap


# ── Progress Tracking (AD-539 Part 7) ───────────────────────────────

async def check_gap_closure(
    gap: GapReport,
    skill_service: Any,
    procedure_store: Any,
) -> bool:
    """Check if a gap has been closed.

    Closure requires:
    1. Skill proficiency reached target level (if mapped)
    2. Procedure effective_rate improved (if procedure evidence)
    """
    from probos.config import GAP_MIN_FAILURE_RATE

    skill_signal = False
    procedure_signal = False

    # Signal 1: Skill proficiency check
    if gap.mapped_skill_id and skill_service:
        try:
            profile = await skill_service.get_profile(gap.agent_id)
            if profile:
                all_skills = list(
                    getattr(profile, "pccs", [])
                    + getattr(profile, "role_skills", [])
                    + getattr(profile, "acquired_skills", [])
                )
                for sr in all_skills:
                    sid = getattr(sr, "skill_id", "")
                    if sid == gap.mapped_skill_id:
                        current = getattr(sr, "proficiency", 0)
                        current = int(current) if not isinstance(current, int) else current
                        if current >= gap.target_proficiency:
                            skill_signal = True
                        break
        except Exception:
            pass

    # Signal 2: Procedure health check
    has_procedure_evidence = any(
        "procedure_" in src for src in gap.evidence_sources
    )
    if has_procedure_evidence and procedure_store:
        try:
            # Extract procedure IDs from evidence
            for src in gap.evidence_sources:
                if ":" in src and "procedure_" in src:
                    parts = src.split(":")
                    proc_id = parts[-1] if len(parts) >= 2 else ""
                    if proc_id:
                        metrics = await procedure_store.get_quality_metrics(proc_id)
                        if metrics:
                            eff_rate = metrics.get("effective_rate", 0.0)
                            if eff_rate > (1.0 - GAP_MIN_FAILURE_RATE):
                                procedure_signal = True
                                break
        except Exception:
            pass
    else:
        # No procedure evidence → only skill signal needed
        procedure_signal = True

    # Both signals required for closure
    if not gap.mapped_skill_id:
        # No skill mapping → only procedure signal matters
        skill_signal = True

    if skill_signal and procedure_signal:
        gap.resolved = True
        gap.resolved_at = time.time()
        return True
    return False
