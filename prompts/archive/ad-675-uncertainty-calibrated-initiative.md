# AD-675: Uncertainty-Calibrated Initiative

**Status:** Ready for builder
**Dependencies:** AD-674 (Graduated Initiative Scale)
**Estimated tests:** ~6

---

## Problem

AD-674 adds `InitiativeLevel` (DIRECTED through STRATEGIC) resolved from
rank + trust score via `resolve_initiative_level()`. This resolution is
deterministic — same rank + trust always produces the same level. But the
system's actual confidence in its observations varies.

When the Oracle returns low-confidence results, or system health indicators
are ambiguous, the initiative system should dial back autonomy. A PROACTIVE
agent should temporarily behave as CONTRIBUTORY if the information driving
its decisions is uncertain.

AD-675 adds uncertainty calibration to initiative level resolution — when
confidence is low, the resolved level is clamped downward.

## Fix

### Section 1: Add `calibrate_initiative()` function

**File:** `src/probos/earned_agency.py`

Add after `resolve_initiative_level()` (added by AD-674):

```python
def calibrate_initiative(
    base_level: "InitiativeLevel",
    confidence: float,
    *,
    low_confidence_threshold: float = 0.4,
    critical_confidence_threshold: float = 0.2,
) -> "InitiativeLevel":
    """Calibrate initiative level by confidence (AD-675).

    When confidence is low, clamp initiative downward:
    - confidence >= low_threshold: no change
    - low_threshold > confidence >= critical_threshold: clamp down 1 level
    - confidence < critical_threshold: clamp down 2 levels (min DIRECTED)

    This prevents agents from acting autonomously when the information
    driving their decisions is uncertain.

    Args:
        base_level: Initiative level from resolve_initiative_level()
        confidence: 0.0-1.0 confidence in current observations
        low_confidence_threshold: Below this, clamp down 1 level
        critical_confidence_threshold: Below this, clamp down 2 levels
    """
    from probos.earned_agency import InitiativeLevel

    if confidence >= low_confidence_threshold:
        return base_level

    current = base_level.value

    if confidence < critical_confidence_threshold:
        clamped = max(0, current - 2)
    else:
        clamped = max(0, current - 1)

    return InitiativeLevel(clamped)
```

### Section 2: Add `UncertaintyContext` dataclass

**File:** `src/probos/earned_agency.py`

Add near the `InitiativeLevel` enum (added by AD-674):

```python
@dataclass(frozen=True)
class UncertaintyContext:
    """Captures confidence factors for initiative calibration (AD-675)."""

    oracle_confidence: float = 1.0  # Oracle result confidence
    health_confidence: float = 1.0  # System health indicator confidence
    data_freshness: float = 1.0     # How recent the data is (1.0 = fresh)

    @property
    def aggregate_confidence(self) -> float:
        """Minimum confidence across all factors."""
        return min(self.oracle_confidence, self.health_confidence, self.data_freshness)
```

Add `from dataclasses import dataclass` to imports if not already present.

## Tests

**File:** `tests/test_ad675_uncertainty_calibrated_initiative.py`

6 tests:

1. `test_high_confidence_no_change` — `calibrate_initiative(PROACTIVE, 0.8)` →
   PROACTIVE (no clamping)
2. `test_low_confidence_clamps_down_one` — `calibrate_initiative(PROACTIVE, 0.3)` →
   CONTRIBUTORY (down 1)
3. `test_critical_confidence_clamps_down_two` — `calibrate_initiative(STRATEGIC, 0.1)` →
   CONTRIBUTORY (down 2, from 4 to 2)
4. `test_directed_stays_directed` — `calibrate_initiative(DIRECTED, 0.1)` →
   DIRECTED (can't go below 0)
5. `test_uncertainty_context_aggregate` — `UncertaintyContext(0.9, 0.3, 0.8)` →
   `aggregate_confidence == 0.3`
6. `test_custom_thresholds` — `calibrate_initiative(PROACTIVE, 0.5, low_confidence_threshold=0.6)` →
   CONTRIBUTORY (custom threshold applies)

## What This Does NOT Change

- `resolve_initiative_level()` unchanged — still deterministic from rank + trust
- `AgencyLevel` enum unchanged
- `ActionGate` / `_classify_trigger()` in InitiativeEngine unchanged
- Does NOT automatically feed Oracle confidence into calibration —
  callers must construct UncertaintyContext and call `calibrate_initiative()`
- Does NOT modify existing agent context injection
- Does NOT add persistence for uncertainty state

## Tracking

- `PROGRESS.md`: Add AD-675 as COMPLETE
- `docs/development/roadmap.md`: Update AD-675 status

## Acceptance Criteria

- `calibrate_initiative()` clamps initiative level based on confidence
- `UncertaintyContext` aggregates multiple confidence factors
- High confidence = no change, low = down 1, critical = down 2
- Clamping never goes below DIRECTED (0)
- All 6 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# AgencyLevel enum
grep -n "class AgencyLevel" src/probos/earned_agency.py
  11: class AgencyLevel(str, Enum)

# AD-674 adds InitiativeLevel after AgencyLevel (line ~16)
# AD-674 adds resolve_initiative_level()
# Both in src/probos/earned_agency.py

# No existing uncertainty/confidence calibration
grep -rn "calibrate_initiative\|UncertaintyContext" src/probos/ → no matches
```
