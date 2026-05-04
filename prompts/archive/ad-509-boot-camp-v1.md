# AD-509 v1: Onboarding Curriculum Pipeline — Boot Camp Phase Tracker

**Status:** Drafted (Wave 25)
**Risk:** low (in-memory tracker; observational)
**Closes:** GitHub issue #91

---

## Solution Overview

AD-509 (roadmap line 6388) describes Boot Camp restructuring: 5 phases, A-School per department, graduated stimuli, completion criteria, trait-adaptive pacing.

**v1 ships 1 of 5 capabilities** — `BootCampPhaseTracker`. Per-agent in-memory phase progression record (orientation → core → a_school → calibration → integration). Read-only observational; no actual phase gating, no Holodeck integration.

**Deferred:**
- AD-509b: A-School per-department curriculum (depends on AD-507 partial-shipped — could be next wave).
- AD-509c: Graduated stimuli + cognitive load monitoring.
- AD-509d: Completion criteria gating (replaces time-based activation).
- AD-509e: Trait-adaptive pacing (depends on AD-486).

## Section 0 — EventTypes

- `BOOT_CAMP_PHASE_ADVANCED` — emitted when an agent's phase advances.

## Section 1 — Files

- `src/probos/crew_development/boot_camp.py` (NEW; ~100 lines; alongside curriculum.py from AD-507)

## Section 2 — `BootCampPhase` enum + `AgentBootCampRecord` dataclass

```python
from enum import Enum

class BootCampPhase(str, Enum):
    """5-phase boot camp progression. AD-509 v1."""
    ORIENTATION = "orientation"
    CORE_KNOWLEDGE = "core_knowledge"
    A_SCHOOL = "a_school"
    CALIBRATION = "calibration"
    INTEGRATION = "integration"
    COMPLETED = "completed"

_PHASE_ORDER: tuple[BootCampPhase, ...] = (
    BootCampPhase.ORIENTATION,
    BootCampPhase.CORE_KNOWLEDGE,
    BootCampPhase.A_SCHOOL,
    BootCampPhase.CALIBRATION,
    BootCampPhase.INTEGRATION,
    BootCampPhase.COMPLETED,
)


@dataclass
class AgentBootCampRecord:
    """Per-agent boot camp phase progression. AD-509 v1."""
    agent_id: str
    current_phase: BootCampPhase = BootCampPhase.ORIENTATION
    started_at: float = field(default_factory=time.time)
    phase_history: list[tuple[str, float]] = field(default_factory=list)  # (phase_value, ts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "current_phase": self.current_phase.value,
            "started_at": self.started_at,
            "phase_history": list(self.phase_history),
        }
```

## Section 3 — `BootCampPhaseTracker`

```python
class BootCampPhaseTracker:
    """In-memory tracker. AD-509 v1.

    Future consumer (AD-509d): completion-criteria gates phase transitions.
    v1 just records advancements caller-driven.
    """

    def __init__(self) -> None:
        self._records: dict[str, AgentBootCampRecord] = {}
        self.emit_event: Callable[..., None] | None = None

    def get_or_create(self, agent_id: str) -> AgentBootCampRecord:
        rec = self._records.get(agent_id)
        if rec is None:
            rec = AgentBootCampRecord(agent_id=agent_id)
            rec.phase_history.append((BootCampPhase.ORIENTATION.value, rec.started_at))
            self._records[agent_id] = rec
        return rec

    def advance_phase(self, agent_id: str) -> BootCampPhase:
        """Advance to next phase. Returns the new current phase."""
        rec = self.get_or_create(agent_id)
        try:
            idx = _PHASE_ORDER.index(rec.current_phase)
        except ValueError:
            return rec.current_phase
        if idx >= len(_PHASE_ORDER) - 1:
            return rec.current_phase  # already at COMPLETED
        next_phase = _PHASE_ORDER[idx + 1]
        prev_phase = rec.current_phase
        rec.current_phase = next_phase
        rec.phase_history.append((next_phase.value, time.time()))
        self._emit(agent_id, prev_phase, next_phase)
        return next_phase

    def get_record(self, agent_id: str) -> AgentBootCampRecord | None:
        return self._records.get(agent_id)

    def all_records(self) -> tuple[AgentBootCampRecord, ...]:
        return tuple(self._records.values())

    def is_completed(self, agent_id: str) -> bool:
        rec = self._records.get(agent_id)
        return rec is not None and rec.current_phase == BootCampPhase.COMPLETED

    def _emit(self, agent_id: str, prev: BootCampPhase, new: BootCampPhase) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.BOOT_CAMP_PHASE_ADVANCED,
                {
                    "agent_id": agent_id,
                    "previous_phase": prev.value,
                    "current_phase": new.value,
                },
            )
        except Exception:
            logger.warning("AD-509: emit_event failed", exc_info=True)
```

## Section 4 — Pydantic config + Section 5 — Wiring

```python
class BootCampConfig(BaseModel):
    enabled: bool = True
```

`SystemConfig.boot_camp`. Sync `_wire_boot_camp_tracker` mirrors AD-525/AD-530 pattern. Public attr: `runtime.boot_camp_tracker`.

## What This Does NOT Change

- AD-509b/c/d/e — all deferred.
- AD-486 Holodeck Birth Chamber — not consumed by v1; tracker is callable from anywhere.
- AD-507 Curriculum Registry — orthogonal (curriculum is content; boot camp is phase progression).
- proactive cognitive loop — not gated by boot camp phase in v1.

## Test Plan

| # | Test |
|---|---|
| 1 | `test_event_type_boot_camp_phase_advanced_exists` |
| 2 | `test_boot_camp_config_defaults` |
| 3 | `test_boot_camp_phase_enum_has_5_phases_plus_completed` |
| 4 | `test_agent_boot_camp_record_initial_state` |
| 5 | `test_get_or_create_idempotent` |
| 6 | `test_get_or_create_seeds_orientation_history_entry` |
| 7 | `test_advance_phase_progresses_through_order` |
| 8 | `test_advance_phase_stops_at_completed` |
| 9 | `test_advance_phase_emits_event` |
| 10 | `test_advance_phase_records_phase_history` |
| 11 | `test_get_record_returns_record_or_none` |
| 12 | `test_all_records_returns_tuple` |
| 13 | `test_is_completed_returns_true_only_at_completed_phase` |
| 14 | `test_runtime_attribute_set_when_enabled` |
| 15 | `test_runtime_attribute_not_set_when_disabled` |

Total: ~15 tests at `tests/test_ad509_boot_camp.py`.

## Tracking

PROGRESS.md / DECISIONS.md (Era V) / roadmap.md (flip AD-509 → partial).

GH #91 closes.

## Verified Against Codebase (2026-05-03)

```
grep -n "_wire_curriculum_registry\|_wire_creative_expression" src/probos/startup/finalize.py
  (Builder verifies sibling pattern; AD-507 just shipped Wave 24)

grep -rn "boot_camp_tracker" src/probos/
  (Expected: 0 hits)
```

## Acceptance Criteria

- 1 new file in src/probos/crew_development/.
- 1 new EventType.
- Public attr runtime.boot_camp_tracker (no underscore).
- Pydantic config wired into SystemConfig.
- ~15 tests pass.
- DECISIONS.md entry under Era V.
- GH #91 closes.

## Hard-Stops

- v1 scope creep — A-School / Holodeck / completion gates / trait-adaptive pacing smuggled in.
- Pre-check finds new phantoms.
