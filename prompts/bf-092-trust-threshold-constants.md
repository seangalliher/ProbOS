# BF-092: Trust Threshold Constants & DRY Cleanup

## Context

Codebase scorecard graded DRY at **B**. Trust thresholds are the system's most important policy constants — they define rank boundaries, escalation triggers, fitness-for-duty gates, and agent lifecycle rules. Yet they're scattered as magic numbers across 15+ files. The `round(trust, 4)` display pattern repeats 52× across 11 files with no centralized precision constant. The `_emit()` event boilerplate is copy-pasted identically in 4 files.

## Problem

Three DRY violations:
1. **~30 hardcoded trust thresholds** outside `config.py` across 15 files — same semantic value repeated, no single source of truth
2. **52 `round(..., 4)` calls** across 11 files — magic precision number, no utility
3. **4 identical `_emit()` method definitions** — textbook copy-paste

## Part 1: Trust Threshold Constants

### New constants in `src/probos/config.py`

Add a new section at module level (NOT inside a Pydantic model — these are system-wide constants, not per-feature config):

```python
# ─── Trust Threshold Constants ─────────────────────────────────────
# Canonical trust boundaries used across the system.
# Rank thresholds define promotion gates in crew_profile.py.
# Other thresholds reference these for consistency.

TRUST_SENIOR = 0.85        # Senior rank promotion threshold
TRUST_COMMANDER = 0.7      # Commander rank promotion threshold
TRUST_LIEUTENANT = 0.5     # Lieutenant rank promotion threshold
TRUST_DEFAULT = 0.5        # Default trust for new/unknown agents
TRUST_FLOOR_CONN = 0.6     # Minimum trust for Conn eligibility
TRUST_FLOOR_CREDIBILITY = 0.3  # Minimum credibility for channel creation
TRUST_DEGRADED = 0.2       # Agent degraded state threshold
TRUST_OUTLIER_LOW = 0.3    # Trust outlier detection — low flag
TRUST_OUTLIER_HIGH = 0.9   # Trust outlier detection — high flag

# Display
TRUST_DISPLAY_PRECISION = 4  # Decimal places for trust/score display
TRUST_COLOR_GREEN = 0.6      # HXI trust color: green above this
TRUST_COLOR_YELLOW = 0.4     # HXI trust color: yellow above this

# Counselor assessment
COUNSELOR_TRUST_PROMOTION = 0.7    # Min trust for promotion fitness
COUNSELOR_WELLNESS_PROMOTION = 0.8 # Min wellness for promotion fitness
COUNSELOR_WELLNESS_YELLOW = 0.5    # Yellow alert wellness threshold
COUNSELOR_WELLNESS_FIT = 0.3       # Minimum wellness for fit-for-duty
COUNSELOR_CONFIDENCE_LOW = 0.3     # Low confidence concern threshold
COUNSELOR_TRUST_DRIFT_CONCERN = -0.2  # Significant trust drop
```

### Consumers to update

Replace each hardcoded value with the named constant. Import from `config.py`.

#### `crew_profile.py` (lines 39, 41, 43) — Rank promotion thresholds
```python
# Before:
if trust_score >= 0.85:
    return cls.SENIOR
elif trust_score >= 0.7:
    return cls.COMMANDER
elif trust_score >= 0.5:
    return cls.LIEUTENANT

# After:
from probos.config import TRUST_SENIOR, TRUST_COMMANDER, TRUST_LIEUTENANT
if trust_score >= TRUST_SENIOR:
    return cls.SENIOR
elif trust_score >= TRUST_COMMANDER:
    return cls.COMMANDER
elif trust_score >= TRUST_LIEUTENANT:
    return cls.LIEUTENANT
```

#### `substrate/agent.py` (lines 38, 121)
- Line 38: `self.trust_score: float = 0.5` → `self.trust_score: float = TRUST_DEFAULT`
- Line 121: `if self.confidence < 0.2:` → `if self.confidence < TRUST_DEGRADED:`

#### `cognitive/counselor.py` (lines 28, 122, 285, 292, 321, 324)
- Line 28: `trust_score: float = 0.5` → `trust_score: float = TRUST_DEFAULT`
- Line 122: `assessment.wellness_score < 0.5` → `< COUNSELOR_WELLNESS_YELLOW`
- Line 285: `trust_drift < -0.2` → `trust_drift < COUNSELOR_TRUST_DRIFT_CONCERN`
- Line 292: `current_confidence < 0.3` → `< COUNSELOR_CONFIDENCE_LOW`
- Line 321: `wellness >= 0.3` → `>= COUNSELOR_WELLNESS_FIT`
- Line 324: `current_trust >= 0.7` → `>= COUNSELOR_TRUST_PROMOTION`

#### `agents/introspect.py` (lines 473, 475)
- Line 473: `score < 0.3` → `score < TRUST_OUTLIER_LOW`
- Line 475: `score > 0.9` → `score > TRUST_OUTLIER_HIGH`

#### `conn.py` (line 63)
- `self._trust_floor: float = 0.6` → `self._trust_floor: float = TRUST_FLOOR_CONN`

#### `runtime.py` (lines 646, 696)
- Line 646: `trust = 0.5` → `trust = TRUST_DEFAULT`
- Line 696: `new_trust >= 0.6` → `new_trust >= TRUST_FLOOR_CONN`

#### `routers/agents.py` (line 71)
- `trust_score = 0.5` → `trust_score = TRUST_DEFAULT`

#### `ward_room.py` (line 629)
- `credibility_score < 0.3` → `credibility_score < TRUST_FLOOR_CREDIBILITY`

#### `experience/panels.py` (lines 33, 34)
- Line 33: `_TRUST_GREEN = 0.6` → `_TRUST_GREEN = TRUST_COLOR_GREEN`
- Line 34: `_TRUST_YELLOW = 0.4` → `_TRUST_YELLOW = TRUST_COLOR_YELLOW`

### What NOT to touch

These are already in config.py Pydantic models — leave them:
- `ConsensusConfig.approval_threshold = 0.6`
- `OnboardingConfig.activation_trust_threshold = 0.65`
- `BridgeAlertConfig.trust_drop_threshold = 0.15`
- `MedicalConfig.trust_floor = 0.3`
- `ProactiveCognitiveConfig.trust_reward_weight = 0.1`

Also leave alone:
- `contradiction_detector.py` `similarity_threshold = 0.85` — this is semantic similarity, not trust
- `cognitive/correction_detector.py` `confidence < 0.5` — correction confidence, not trust
- `cognitive/strategy_extraction.py` `confidence: float = 0.5` — strategy confidence
- `cognitive/emergent_detector.py` `confidence=0.7` — pattern confidence
- `cognitive/behavioral_monitor.py` `_HIGH_FAILURE_THRESHOLD = 0.5` — failure rate, not trust
- `proactive.py` `threshold: float = 0.5` — similarity threshold
- `cognitive/strategy.py` `_DOMAIN_MATCH_THRESHOLD = 0.3` — domain matching
- `ward_room.py` `credibility_score: float = 0.5` — default dataclass field (separate from the comparison)
- `workforce.py` `min_trust=0.6` — already a parameter default, could optionally reference constant but not required
- `acm.py` `threshold: float = 0.65` — mirrors `OnboardingConfig`, could reference but not required

The rule: only replace magic numbers that represent **trust policy thresholds used in conditional logic**. Don't replace parameter defaults that are already configurable, similarity scores, or non-trust confidence values.

## Part 2: Trust Display Utility

### Add `format_trust()` to `config.py`

```python
def format_trust(value: float, precision: int = TRUST_DISPLAY_PRECISION) -> float:
    """Round a trust/score value for display. Centralizes precision."""
    return round(value, precision)
```

### Replace `round(..., 4)` calls

In all 11 files with `round(something, 4)` for trust/score display, replace with `format_trust(something)`.

**Files to update** (52 occurrences total):
- `agents/introspect.py` — 18 occurrences
- `runtime.py` — 10 occurrences
- `cognitive/emergent_detector.py` — 7 occurrences (note: some use `round(..., 3)` — use `format_trust(value, 3)` for those)
- `consensus/trust.py` — 4 occurrences (note: `round(r.alpha, 2)` and `round(r.beta, 2)` use precision 2 — use `format_trust(value, 2)`)
- `dream_adapter.py` — 3 occurrences
- `routers/agents.py` — 3 occurrences
- `substrate/agent.py` — 3 occurrences
- `ward_room.py` — 2 occurrences
- `proactive.py` — 2 occurrences
- `acm.py` — 1 occurrence
- `agent_onboarding.py` — 1 occurrence

Import: `from probos.config import format_trust`

**Rule:** Only replace `round(x, N)` calls where `x` is a trust score, confidence, weight, or similar metric value. Do NOT replace `round()` calls on unrelated values (e.g., percentages, counts, coordinates).

## Part 3: EventEmitterMixin

### Create mixin in `src/probos/protocols.py`

Add alongside the existing Protocols:

```python
class EventEmitterMixin:
    """Mixin for classes that emit events via an optional callback."""

    _emit_event: Callable[[str, dict[str, Any]], None] | None

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self._emit_event:
            self._emit_event(event_type, data)
```

### Consumers to update (4 files — Pattern A)

Remove the duplicated `_emit()` method definition from each file. Add `EventEmitterMixin` to the class's bases.

#### `assignment.py` (line ~114)
```python
# Before:
class AssignmentEngine:
    def __init__(self, ..., emit_event=None):
        self._emit_event = emit_event

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self._emit_event:
            self._emit_event(event_type, data)

# After:
from probos.protocols import EventEmitterMixin

class AssignmentEngine(EventEmitterMixin):
    def __init__(self, ..., emit_event=None):
        self._emit_event = emit_event
    # _emit() inherited from mixin
```

#### `persistent_tasks.py` (line ~175)
Same pattern — add `EventEmitterMixin` to class bases, remove `_emit()` definition.

#### `ward_room.py` (line ~515)
Same pattern.

#### `workforce.py` (line ~984)
Same pattern.

### What NOT to touch

- `task_tracker.py` — its two `_emit()` variants have different signatures (typed domain objects + serialization). These are NOT duplicates of Pattern A — leave them.
- `bridge_alerts.py` `_should_emit()` — deduplication guard, different purpose.
- Direct `self._event_emitter(...)` calls in `agent_onboarding.py`, `dream_adapter.py`, `self_mod_manager.py` — different pattern (no guard), leave as-is.

## Verification

After all changes:

1. **Constants:** `grep -rn "0\.85\|0\.7[^0-9]\|>= 0\.5\|< 0\.3\|< 0\.2" src/probos/ --include="*.py" | grep -v config.py | grep -v test` — should show only non-trust uses (similarity, confidence, etc.)
2. **Display:** `grep -rn "round(.*4)" src/probos/ --include="*.py" | grep -v config.py | grep -v test` — should be zero (all replaced with `format_trust()`)
3. **Emit:** `grep -rn "def _emit" src/probos/ --include="*.py"` — should show only `protocols.py` (mixin) and `task_tracker.py` (two variants)
4. Run targeted tests: `python -m pytest tests/ -x -q --tb=short`
5. Run full suite: `python -m pytest tests/ -q --tb=short` — expect 4243+ passing

## Principles Compliance

- **DRY**: Three violations eliminated — thresholds centralized, display precision extracted, emit boilerplate deduplicated
- **SOLID (O)**: Constants can be overridden by commercial config without modifying consumer code
- **SOLID (D)**: Mixin provides the abstraction; consumers depend on the interface
- **Cloud-Ready**: Centralized thresholds mean commercial overlay can tune trust policy from one location

## What NOT to Do

- Do NOT change any threshold VALUES — only move them to named constants
- Do NOT modify test files
- Do NOT change the behavior of any `_emit()` call — only deduplicate the definition
- Do NOT replace `round()` calls on non-trust values
- Do NOT move existing config.py Pydantic model fields — they're already centralized
- Line numbers are approximate — find the nearest matching pattern if lines have shifted
