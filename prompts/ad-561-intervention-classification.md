# AD-561: Intervention Classification

**Status:** Ready for builder
**Dependencies:** None
**Estimated tests:** ~13

---

## Problem

The Counselor performs four types of interventions (therapeutic DM, cooldown
extension, forced dream cycle, guidance directive) but they're all tracked
ad-hoc. There's no structured classification, no event emission per
intervention, and no way to query "how many cooldown extensions has the
Counselor issued this session?" or "which agents received guidance directives?"

## Fix

### Section 1: Create `InterventionType` enum and `InterventionRecord`

**File:** `src/probos/cognitive/counselor.py`

Add at module level (after the existing imports, before the class definition).

**IMPORTANT:** counselor.py does NOT currently import `Enum` or `time`. Add
these imports near the top of the file (after line 16 `from dataclasses import dataclass, field`):

```python
import time
from enum import Enum
```

Then add the enum and dataclass:

```python
class InterventionType(str, Enum):
    """Classification of Counselor interventions (AD-561)."""

    THERAPEUTIC_DM = "therapeutic_dm"
    COOLDOWN_EXTENSION = "cooldown_extension"
    FORCED_DREAM = "forced_dream"
    GUIDANCE_DIRECTIVE = "guidance_directive"
    TRUST_ADJUSTMENT = "trust_adjustment"


@dataclass
class InterventionRecord:
    """Structured record of a Counselor intervention (AD-561)."""

    intervention_type: InterventionType
    agent_id: str
    callsign: str
    trigger: str  # "circuit_breaker" | "sweep" | "trust_update" | "conduct_violation" | "zone"
    severity: str  # "concern" | "intervention" | "escalate"
    detail: str
    timestamp: float = field(default_factory=time.time)
```

Verify the required imports. Grep for existing imports:
```
grep -n "from enum import\|from dataclasses import" src/probos/cognitive/counselor.py
```

### Section 2: Add `COUNSELOR_INTERVENTION` event type

**File:** `src/probos/events.py`

Add after the existing `COUNSELOR_ASSESSMENT` (line 123):

SEARCH:
```python
    COUNSELOR_ASSESSMENT = "counselor_assessment"
```

REPLACE:
```python
    COUNSELOR_ASSESSMENT = "counselor_assessment"
    COUNSELOR_INTERVENTION = "counselor_intervention"  # AD-561
```

### Section 3: Add intervention tracking to CounselorAgent

**File:** `src/probos/cognitive/counselor.py`

**Step 1:** Add intervention history list to `__init__` (after existing
attribute initializations around lines 520-525):

```python
        # AD-561: Intervention tracking
        self._intervention_history: list[InterventionRecord] = []
```

**Step 2:** Add `_record_intervention()` method that creates a record and
emits an event:

```python
    def _record_intervention(
        self,
        intervention_type: InterventionType,
        agent_id: str,
        callsign: str,
        trigger: str,
        severity: str,
        detail: str,
    ) -> InterventionRecord:
        """Record and emit a classified intervention (AD-561)."""
        record = InterventionRecord(
            intervention_type=intervention_type,
            agent_id=agent_id,
            callsign=callsign,
            trigger=trigger,
            severity=severity,
            detail=detail,
        )
        self._intervention_history.append(record)
        # Emit event for subscribers
        if self._emit_event_fn:
            from probos.events import EventType
            self._emit_event_fn(EventType.COUNSELOR_INTERVENTION, {
                "intervention_type": intervention_type.value,
                "agent_id": agent_id,
                "callsign": callsign,
                "trigger": trigger,
                "severity": severity,
                "detail": detail,
                "timestamp": record.timestamp,
            })
        return record
```

Verify `_emit_event_fn` attribute exists. Grep for:
```
grep -n "_emit_event_fn\|_emit_event" src/probos/cognitive/counselor.py | head -10
```

If the Counselor uses a different event emission pattern, follow that pattern instead.

**Step 3:** Instrument existing intervention methods. Add `_record_intervention()`
calls to each intervention site:

**In `_send_therapeutic_dm()` (line ~2060)** — after a successful DM send:

Find the success path (after the ward_room thread creation succeeds):
```python
            self._record_intervention(
                InterventionType.THERAPEUTIC_DM,
                agent_id=agent_id,
                callsign=callsign,
                trigger="",  # set by caller
                severity="concern",
                detail=f"Therapeutic DM sent: {message[:100]}...",
            )
```

**In `_apply_intervention()` (line ~2377)** — after each of the three
intervention types:

After cooldown extension (around line 2407):
```python
                self._record_intervention(
                    InterventionType.COOLDOWN_EXTENSION,
                    agent_id=agent_id,
                    callsign=callsign,
                    trigger=assessment.trigger if hasattr(assessment, 'trigger') else "",
                    severity=severity,
                    detail=f"Cooldown extended to {new_cooldown:.0f}s (multiplier {multiplier}x)",
                )
```

After forced dream (around line 2419):
```python
                self._record_intervention(
                    InterventionType.FORCED_DREAM,
                    agent_id=agent_id,
                    callsign=callsign,
                    trigger=assessment.trigger if hasattr(assessment, 'trigger') else "",
                    severity=severity,
                    detail="Forced dream cycle initiated",
                )
```

After guidance directive (around line 2434):
```python
                self._record_intervention(
                    InterventionType.GUIDANCE_DIRECTIVE,
                    agent_id=agent_id,
                    callsign=callsign,
                    trigger=assessment.trigger if hasattr(assessment, 'trigger') else "",
                    severity=severity,
                    detail=f"Directive issued: {content[:100]}...",
                )
```

### Section 4: Add intervention query methods

**File:** `src/probos/cognitive/counselor.py`

Add methods for querying intervention history:

```python
    def get_intervention_history(
        self,
        *,
        agent_id: str = "",
        intervention_type: InterventionType | None = None,
        limit: int = 50,
    ) -> list[InterventionRecord]:
        """Query intervention history with optional filters (AD-561)."""
        results = self._intervention_history
        if agent_id:
            results = [r for r in results if r.agent_id == agent_id]
        if intervention_type:
            results = [r for r in results if r.intervention_type == intervention_type]
        return results[-limit:]

    def get_intervention_summary(self) -> dict[str, int]:
        """Return counts by intervention type (AD-561)."""
        counts: dict[str, int] = {}
        for record in self._intervention_history:
            key = record.intervention_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts
```

### Section 5: Add intervention API endpoint

**File:** `src/probos/routers/counselor.py`

Add a `GET /api/counselor/interventions` endpoint. Use the existing
`_get_counselor_agent()` helper (line 118) which looks up the Counselor
from the pool registry — do NOT use `runtime._counselor` (it doesn't exist):

```python
@router.get("/interventions")
async def get_interventions(runtime: Any = Depends(get_runtime)) -> dict:
    """Return Counselor intervention summary (AD-561)."""
    counselor = _get_counselor_agent(runtime)
    if not counselor:
        return {"status": "no_counselor", "summary": {}, "recent": []}
    return {
        "summary": counselor.get_intervention_summary(),
        "recent": [
            {
                "type": r.intervention_type.value,
                "agent_id": r.agent_id,
                "callsign": r.callsign,
                "trigger": r.trigger,
                "severity": r.severity,
                "detail": r.detail,
                "timestamp": r.timestamp,
            }
            for r in counselor.get_intervention_history(limit=20)
        ],
    }
```

Verify how the Counselor is stored on the runtime. Grep for:
```
grep -n "_counselor\|counselor_agent" src/probos/startup/
```

## Tests

**File:** `tests/test_ad561_intervention_classification.py`

13 tests:

1. `test_intervention_type_enum_values` — verify all 5 `InterventionType` values exist
2. `test_intervention_record_creation` — create an `InterventionRecord`, verify fields
3. `test_intervention_record_default_timestamp` — verify auto-timestamp
4. `test_counselor_intervention_event_type` — verify `EventType.COUNSELOR_INTERVENTION` exists
5. `test_record_intervention_appends_to_history` — call `_record_intervention()`,
   verify it appears in `_intervention_history`
6. `test_record_intervention_emits_event` — mock `_emit_event_fn`, call
   `_record_intervention()`, verify event emitted with correct type and data
7. `test_therapeutic_dm_records_intervention` — mock ward_room, call
   `_send_therapeutic_dm()`, verify `InterventionType.THERAPEUTIC_DM` recorded
8. `test_cooldown_extension_records_intervention` — mock dependencies, trigger
   `_apply_intervention()` with cooldown path, verify `COOLDOWN_EXTENSION` recorded
9. `test_forced_dream_records_intervention` — mock dream_scheduler, trigger
   `_apply_intervention()`, verify `FORCED_DREAM` recorded
10. `test_guidance_directive_records_intervention` — mock directive_store, trigger
    directive issuance, verify `GUIDANCE_DIRECTIVE` recorded
11. `test_get_intervention_history_filter_by_agent` — add multiple records,
    filter by agent_id, verify correct subset
12. `test_get_intervention_history_filter_by_type` — filter by InterventionType,
    verify correct subset
13. `test_get_intervention_summary` — add mixed records, verify counts dict

## What This Does NOT Change

- No changes to the intervention logic itself — same conditions, same thresholds
- No changes to CounselorAssessment or wellness scoring
- No persistence of intervention history — in-memory only (resets on restart).
  Persistence is a future enhancement.
- Does NOT add automated intervention triggers — Counselor still decides when
  to intervene based on existing event-driven logic
- Does NOT modify the Counselor's event subscription list

## Tracking

- `PROGRESS.md`: Add AD-561 as COMPLETE
- `docs/development/roadmap.md`: Update AD-561 status

## Acceptance Criteria

- `InterventionType` enum with 5 types exists
- `InterventionRecord` dataclass captures all intervention metadata
- All 4 intervention paths emit classified events
- `get_intervention_history()` and `get_intervention_summary()` work with filters
- `GET /api/interventions` endpoint returns summary and recent interventions
- `EventType.COUNSELOR_INTERVENTION` exists in events.py
- All 13 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# Counselor intervention methods
grep -n "_send_therapeutic_dm\|_apply_intervention\|_issue_guidance_directive" \
  src/probos/cognitive/counselor.py
  2060: async def _send_therapeutic_dm(self, agent_id, callsign, message)
  2160: async def _maybe_send_therapeutic_dm(self, agent_id, callsign, assessment, trigger)
  2324: def _issue_guidance_directive(self, target_agent_type, content, expires_hours=24.0)
  2377: async def _apply_intervention(self, agent_id, callsign, assessment, severity)

# Existing event
grep -n "COUNSELOR_ASSESSMENT" src/probos/events.py
  123: COUNSELOR_ASSESSMENT = "counselor_assessment"

# CounselorAgent __init__ attributes
grep -n "self._dm_cooldowns\|self._intervention_targets" src/probos/cognitive/counselor.py
  524: self._dm_cooldowns: dict[str, float] = {}
  525: self._intervention_targets: set[str] = set()

# No existing intervention classification
grep -rn "InterventionType\|InterventionRecord" src/probos/ → no matches

# Event emission pattern in Counselor
grep -n "_emit_event" src/probos/cognitive/counselor.py | head -5
  → check for _emit_event_fn or similar callback pattern
```
