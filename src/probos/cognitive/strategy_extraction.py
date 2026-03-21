"""AD-383: Strategy extraction — cross-agent transferable patterns from experience."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StrategyType(str, Enum):
    ERROR_RECOVERY = "error_recovery"      # retry/fallback patterns
    PROMPT_TECHNIQUE = "prompt_technique"   # prompt patterns that improve quality
    COORDINATION = "coordination"          # multi-agent cooperation patterns
    OPTIMIZATION = "optimization"          # efficiency improvements


@dataclass
class StrategyPattern:
    """A transferable pattern extracted from cross-agent experience."""
    id: str  # hash of type + description for dedup
    strategy_type: StrategyType
    description: str  # human-readable description of the strategy
    applicability: str  # when/where this strategy applies
    source_agents: list[str]  # agent types that demonstrated this pattern
    source_intent_types: list[str]  # intent types where this was observed
    evidence_count: int = 1  # how many episodes support this pattern
    confidence: float = 0.5  # how well-supported (0.0-1.0)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @staticmethod
    def make_id(strategy_type: str, description: str) -> str:
        """Deterministic ID for dedup."""
        raw = f"{strategy_type}:{description}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def reinforce(self, count: int = 1) -> None:
        """Reinforce this strategy with additional evidence.

        Increments evidence_count, increases confidence toward 1.0.
        confidence = min(1.0, 1.0 - 1.0 / (evidence_count + 1))
        """
        self.evidence_count += count
        self.confidence = min(1.0, 1.0 - 1.0 / (self.evidence_count + 1))
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "strategy_type": self.strategy_type.value,
            "description": self.description,
            "applicability": self.applicability,
            "source_agents": self.source_agents,
            "source_intent_types": self.source_intent_types,
            "evidence_count": self.evidence_count,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StrategyPattern:
        return cls(
            id=d["id"],
            strategy_type=StrategyType(d["strategy_type"]),
            description=d["description"],
            applicability=d["applicability"],
            source_agents=d.get("source_agents", []),
            source_intent_types=d.get("source_intent_types", []),
            evidence_count=d.get("evidence_count", 1),
            confidence=d.get("confidence", 0.5),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
        )


def extract_strategies(
    episodes: list,
    min_occurrences: int = 3,
) -> list[StrategyPattern]:
    """Extract transferable strategies from episodic memory.

    Scans episodes for cross-agent recurring patterns:

    1. **Error -> Recovery patterns**: Group episodes by error type.
       When the same error pattern appears across 2+ agent types and
       at least one had a successful retry/recovery, extract the recovery
       as a strategy.

    2. **High-confidence intent patterns**: Group successful episodes by
       intent type. When an intent type has consistent high confidence
       (>= 0.8) across multiple agents, extract the common approach.

    3. **Co-occurrence patterns**: Identify intent pairs that frequently
       co-occur in the same session (within 60s). When the same pair
       appears `min_occurrences` times, extract as a coordination strategy.

    Each episode is expected to have at minimum:
    - `agent_type` (str)
    - `intent` (str) -- the intent name
    - `outcome` (dict or object) with `success` (bool), `confidence` (float)
    - `timestamp` (float)
    - `error` (str | None) -- error message if failed

    Returns deduplicated list of StrategyPattern objects.
    """
    strategies: dict[str, StrategyPattern] = {}

    # Pattern 1: Error -> Recovery
    error_groups: dict[str, list] = {}
    for ep in episodes:
        err = _get_field(ep, 'error', None)
        if err:
            sig = err[:50].strip()
            error_groups.setdefault(sig, []).append(ep)

    for sig, group in error_groups.items():
        if len(group) < min_occurrences:
            continue
        agent_types: set[str] = set()
        has_recovery = False
        intent_types: set[str] = set()
        for ep in group:
            agent_types.add(_get_field(ep, 'agent_type', ''))
            intent_types.add(_get_field(ep, 'intent', ''))
            outcome = _get_field(ep, 'outcome', {})
            if isinstance(outcome, dict) and outcome.get('success'):
                has_recovery = True
        if len(agent_types) >= 2 and has_recovery:
            desc = f"Recovery from: {sig}"
            sid = StrategyPattern.make_id("error_recovery", desc)
            if sid not in strategies:
                strategies[sid] = StrategyPattern(
                    id=sid,
                    strategy_type=StrategyType.ERROR_RECOVERY,
                    description=desc,
                    applicability=f"When encountering: {sig}",
                    source_agents=sorted(agent_types),
                    source_intent_types=sorted(intent_types),
                    evidence_count=len(group),
                )
            else:
                strategies[sid].reinforce(len(group))

    # Pattern 2: High-confidence intent patterns
    intent_success: dict[str, list] = {}
    for ep in episodes:
        outcome = _get_field(ep, 'outcome', {})
        success = outcome.get('success') if isinstance(outcome, dict) else getattr(outcome, 'success', False)
        if success:
            intent = _get_field(ep, 'intent', '')
            if intent:
                intent_success.setdefault(intent, []).append(ep)

    for intent, group in intent_success.items():
        if len(group) < min_occurrences:
            continue
        agent_types_set: set[str] = set()
        confidences: list[float] = []
        for ep in group:
            agent_types_set.add(_get_field(ep, 'agent_type', ''))
            outcome = _get_field(ep, 'outcome', {})
            conf = outcome.get('confidence', 0.0) if isinstance(outcome, dict) else getattr(outcome, 'confidence', 0.0)
            confidences.append(conf)
        if len(agent_types_set) >= 2 and confidences and (sum(confidences) / len(confidences)) >= 0.8:
            desc = f"High-confidence approach for {intent}"
            sid = StrategyPattern.make_id("prompt_technique", desc)
            if sid not in strategies:
                strategies[sid] = StrategyPattern(
                    id=sid,
                    strategy_type=StrategyType.PROMPT_TECHNIQUE,
                    description=desc,
                    applicability=f"When handling {intent} intents",
                    source_agents=sorted(agent_types_set),
                    source_intent_types=[intent],
                    evidence_count=len(group),
                    confidence=sum(confidences) / len(confidences),
                )

    # Pattern 3: Co-occurrence (intent pairs within 60s window)
    sorted_eps = sorted(episodes, key=lambda e: _get_field(e, 'timestamp', 0.0))
    pair_counts: dict[tuple[str, str], list[set[str]]] = {}
    for i, ep in enumerate(sorted_eps):
        t = _get_field(ep, 'timestamp', 0.0)
        intent_a = _get_field(ep, 'intent', '')
        if not intent_a:
            continue
        for j in range(i + 1, len(sorted_eps)):
            t2 = _get_field(sorted_eps[j], 'timestamp', 0.0)
            if t2 - t > 60.0:
                break
            intent_b = _get_field(sorted_eps[j], 'intent', '')
            if intent_b and intent_b != intent_a:
                pair = tuple(sorted([intent_a, intent_b]))
                if pair not in pair_counts:
                    pair_counts[pair] = []
                agents = {_get_field(ep, 'agent_type', ''), _get_field(sorted_eps[j], 'agent_type', '')}
                pair_counts[pair].append(agents)

    for pair, agent_sets in pair_counts.items():
        if len(agent_sets) < min_occurrences:
            continue
        all_agents: set[str] = set()
        for s in agent_sets:
            all_agents.update(s)
        desc = f"Coordination: {pair[0]} + {pair[1]}"
        sid = StrategyPattern.make_id("coordination", desc)
        if sid not in strategies:
            strategies[sid] = StrategyPattern(
                id=sid,
                strategy_type=StrategyType.COORDINATION,
                description=desc,
                applicability=f"When {pair[0]} and {pair[1]} co-occur",
                source_agents=sorted(all_agents),
                source_intent_types=sorted(pair),
                evidence_count=len(agent_sets),
            )

    return list(strategies.values())


def _get_field(obj: Any, name: str, default: Any) -> Any:
    """Get a field from either a dict or an object."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
