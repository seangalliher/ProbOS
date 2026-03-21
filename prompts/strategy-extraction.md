# AD-383: Strategy Extraction — Dream-Derived Transferable Patterns

## Goal

Add a strategy extraction pass to the DreamingEngine. Today, dream consolidation strengthens/weakens Hebbian weights and adjusts trust, but no cross-agent patterns are extracted. When a sentiment agent learns a useful approach (e.g., "retry with rephrased prompt on low confidence"), that knowledge can't help the file agent or any future agent. This AD extracts transferable `StrategyPattern` objects from episodic memory during dream cycles and persists them in the KnowledgeStore.

## Architecture

**Pattern:** New dream pass, integrated into the existing `DreamScheduler` full dream cycle (not micro-dreams). Strategy extraction runs after the existing 4 steps (replay, prune, trust consolidation, pre-warm).

## Reference Files (read these first)

- `src/probos/cognitive/dreaming.py` — `DreamEngine`, `DreamScheduler`, `DreamReport`, `dream_cycle()`, existing 4 passes
- `src/probos/knowledge/store.py` — `KnowledgeStore` with `store_artifact()`, `search_by_keywords()`
- `src/probos/mesh/routing.py` — `HebbianRouter`, `REL_INTENT`, relationship types

## Files to Create

### `src/probos/cognitive/strategy.py` (~200 lines)

```python
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

    1. **Error → Recovery patterns**: Group episodes by error type.
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
    - `intent` (str) — the intent name
    - `outcome` (dict or object) with `success` (bool), `confidence` (float)
    - `timestamp` (float)
    - `error` (str | None) — error message if failed

    Returns deduplicated list of StrategyPattern objects.
    """
    strategies: dict[str, StrategyPattern] = {}

    # Pattern 1: Error → Recovery
    # Group episodes by simplified error signature (first 50 chars of error)
    # For each error group:
    #   - If 2+ agent types experienced it AND at least one succeeded after failure
    #   - Extract as ERROR_RECOVERY strategy
    error_groups: dict[str, list] = {}
    for ep in episodes:
        err = getattr(ep, 'error', None) or (ep.get('error') if isinstance(ep, dict) else None)
        if err:
            sig = err[:50].strip()
            error_groups.setdefault(sig, []).append(ep)

    for sig, group in error_groups.items():
        if len(group) < min_occurrences:
            continue
        agent_types = set()
        has_recovery = False
        intent_types = set()
        for ep in group:
            at = _get_field(ep, 'agent_type', '')
            agent_types.add(at)
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
    # Group successful episodes by intent type
    # For each intent: if avg confidence >= 0.8 across 2+ agent types
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
        agent_types = set()
        confidences = []
        for ep in group:
            agent_types.add(_get_field(ep, 'agent_type', ''))
            outcome = _get_field(ep, 'outcome', {})
            conf = outcome.get('confidence', 0.0) if isinstance(outcome, dict) else getattr(outcome, 'confidence', 0.0)
            confidences.append(conf)
        if len(agent_types) >= 2 and confidences and (sum(confidences) / len(confidences)) >= 0.8:
            desc = f"High-confidence approach for {intent}"
            sid = StrategyPattern.make_id("prompt_technique", desc)
            if sid not in strategies:
                strategies[sid] = StrategyPattern(
                    id=sid,
                    strategy_type=StrategyType.PROMPT_TECHNIQUE,
                    description=desc,
                    applicability=f"When handling {intent} intents",
                    source_agents=sorted(agent_types),
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
        all_agents = set()
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


def _get_field(obj, name: str, default: Any) -> Any:
    """Get a field from either a dict or an object."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
```

## Files to Modify

### `src/probos/cognitive/dreaming.py`

1. Add import: `from probos.cognitive.strategy import extract_strategies, StrategyPattern`
2. Add `strategies_extracted: int = 0` field to `DreamReport`
3. In `DreamEngine.dream_cycle()`, after step 4 (pre-warm) and before returning the report, add step 5:

```python
# Step 5: Strategy extraction (AD-383)
strategies = extract_strategies(episodes, min_occurrences=3)
report.strategies_extracted = len(strategies)
if strategies and self._strategy_store_fn:
    self._strategy_store_fn(strategies)
```

4. Add `_strategy_store_fn: Callable | None = None` to `DreamEngine.__init__()` as a new parameter `strategy_store_fn=None`
5. Add `strategy_store_fn: Callable | None = None` to `DreamScheduler.__init__()` — pass through to the DreamEngine

Note: The `_strategy_store_fn` callback receives a `list[StrategyPattern]`. The runtime will wire this to persist strategies to the KnowledgeStore. But the DreamEngine itself does not import or depend on KnowledgeStore — loose coupling via callback.

### `src/probos/runtime.py`

1. Wire the strategy store callback when creating DreamScheduler:
   ```python
   # In start(), where DreamScheduler is created:
   strategy_store_fn = self._store_strategies if self.knowledge_store else None
   ```
2. Add `_store_strategies(self, strategies: list)` method:
   ```python
   def _store_strategies(self, strategies: list) -> None:
       """Persist dream-extracted strategies to knowledge store."""
       if not self.knowledge_store:
           return
       for s in strategies:
           self.knowledge_store.store_artifact(
               key=f"strategy:{s.id}",
               data=s.to_dict(),
               category="strategy",
               keywords=[s.strategy_type.value] + s.source_intent_types,
           )
   ```

Note: Read the actual KnowledgeStore API before implementing — verify the `store_artifact()` signature matches.

## Tests

### Create `tests/test_strategy.py` (~160 lines)

1. **`test_strategy_pattern_make_id`** — Deterministic ID from type + description
2. **`test_strategy_pattern_make_id_deterministic`** — Same inputs → same ID
3. **`test_strategy_reinforce`** — evidence_count increases, confidence approaches 1.0
4. **`test_strategy_roundtrip`** — `to_dict()` → `from_dict()` preserves all fields
5. **`test_extract_error_recovery_cross_agent`** — 5 episodes: 3 agent types, same error, 1 recovery → ERROR_RECOVERY strategy
6. **`test_extract_error_recovery_single_agent_no_match`** — Same error but only 1 agent type → no strategy (requires 2+)
7. **`test_extract_error_recovery_below_min_occurrences`** — Only 2 episodes (min=3) → no strategy
8. **`test_extract_high_confidence_pattern`** — 5 successful episodes across 2 agent types, avg confidence 0.9 → PROMPT_TECHNIQUE strategy
9. **`test_extract_high_confidence_low_avg`** — avg confidence 0.5 → no strategy
10. **`test_extract_coordination_pattern`** — 4 co-occurring intent pairs within 60s → COORDINATION strategy
11. **`test_extract_coordination_outside_window`** — Pairs separated by 120s → no strategy
12. **`test_extract_dedup`** — Same pattern appears multiple times → single strategy with reinforced count
13. **`test_extract_empty_episodes`** — Empty list → empty result
14. **`test_get_field_dict`** — Works with dict input
15. **`test_get_field_object`** — Works with object input

Use simple dicts for episodes in tests (the `_get_field()` helper supports both dicts and objects):
```python
episode = {
    "agent_type": "file_reader",
    "intent": "read_file",
    "outcome": {"success": True, "confidence": 0.9},
    "timestamp": 1000.0,
    "error": None,
}
```

## Constraints

- No LLM calls — purely programmatic pattern matching
- Episodes can be dicts or objects (use `_get_field()` for both)
- `DreamReport.strategies_extracted` defaults to 0 — backward compatible
- `strategy_store_fn` defaults to None — no behavior change if not wired
- Do not modify the existing 4 dream passes (replay, prune, trust, pre-warm)
