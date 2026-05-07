# AD-628 v1: Crew Skill Readiness Monitoring + Training Officer Role

**Status:** Drafted, awaiting build
**Issue:** #223
**Wave:** 93
**Depends:** AD-535 (SkillFramework), AD-428b (composite skills), AD-566f (qual_skill_bridge), AD-477 (QualificationHarness), AD-515 (AgentOnboardingService), AD-506a (CognitiveZone), AD-339 (Standing Orders), AD-625 (CommTier)
**Estimated tests:** ~70 (floor +66 vs baseline 12041 → target ≥ 12107)

---

## Problem

AD-625/626/627 established the communication-discipline cognitive skill and augmentation injection pipeline, but there is **no feedback loop** — no agent can observe whether skills are loading, whether proficiency gates are blocking, or whether agents are actually following skill instructions. Medical agents diagnose crew cognitive health (AD-506a Cognitive Zones) but have **zero visibility into skill telemetry**. The Counselor monitors behavioral drift (AD-566c) but cannot correlate with skill proficiency trends. The codebase exposes:

- **No `SKILL_*` EventType** (`Select-String -Path src\probos\events.py -Pattern 'SKILL_(LOADED|BLOCKED|EXERCISED|REGRESSION|DECAY|ACQUIRED)'` returns zero — verified at HEAD `c6c38ec`).
- **No agent-readiness aggregator** over skill state + qualification advancements + decay events.
- **No drill-scheduling primitive** that ties qualification tests to a calendar.
- **No mentor-announcer hook** in `agent_onboarding.py` for new-agent welcome flow.
- **No readiness-reporting surface** at ship-wide or per-department granularity.
- **No LIMDU-equivalent protocol** for joint Medical+TRAINO reduced-duty recommendation.
- **No Training Officer crew agent** in the assignments table (`organization.yaml:325`–`:386` lists 14 crew-agent assignments; the 15th — TRAINO — is missing).

The Navy solves the same problem via PQS (qualification standards) + COSC (stress continuum) + IMR (medical readiness) + a dedicated Training Officer role with C-rating readiness reporting to the CO. AD-628 ports the decomposition.

## Solution

Eight implementation sections shipping eight sub-AD letters in v1 (a/b/c/d/e/f/g/h):

| Section | Sub-AD | Surface | Tests |
|---|---|---|---|
| 1 | 628a | New `EventType` values + `AgentSkillService.set_event_emitter` + emission inside the four mutation methods | ~10 |
| 2 | 628b | New `src/probos/cognitive/skill_readiness.py` with `AgentSkillReadinessProfile` + `AgentSkillReadinessService` | ~8 |
| 3 | 628c | New `config/standing_orders/crew_profiles/training_officer.yaml` + `chief_training` post + `Tucker` assignment in `organization.yaml` | ~6 |
| 4 | 628d | New `src/probos/cognitive/drill_calendar.py` with `DrillEntry` + `DrillCalendar` queue layered on AD-477 | ~10 |
| 5 | 628e | `AgentOnboardingService.register_mentor_announcer(announcer)` setter + invocation block at `agent_onboarding.py:233` (just before the AD-499 self-naming event-log) | ~6 |
| 6 | 628f | New `src/probos/cognitive/readiness_reporter.py` with `DepartmentReadinessReport` + `ShipReadinessReport` + `ReadinessReporter` | ~10 |
| 7 | 628g | New `src/probos/cognitive/limdu.py` with `LIMDURecommendation` + `LIMDUService.recommend_limited_duty` (joint-authority required-kwargs) + new `LIMDU_RECOMMENDED` EventType | ~10 |
| 8 | 628h | New `cmd_readiness` slash command in `experience/commands/commands_status.py` | ~6 |

Plus startup wiring tests (~4) for service registration on `runtime.py` startup.

---

## Section 0: New EventType values

Add seven new values to `EventType` in `src/probos/events.py` after the existing `WARD_ROOM_ENDORSEMENT` block. Insertion point determined by grep:

```
Select-String -Path src\probos\events.py -Pattern "WARD_ROOM_ENDORSEMENT|^class EventType" | Select-Object LineNumber, Line
```

Verified positions: `class EventType` at line 20; `WARD_ROOM_ENDORSEMENT = "ward_room_endorsement"` at line 69. Insert the new block **after line 69** (after the Ward Room block), **before** the `# Dream / system mode` comment block.

```
===MODIFY: src/probos/events.py===
===SEARCH===
    WARD_ROOM_ENDORSEMENT = "ward_room_endorsement"

    # Dream / system mode
===REPLACE===
    WARD_ROOM_ENDORSEMENT = "ward_room_endorsement"

    # Skill telemetry (AD-628a)
    SKILL_LOADED = "skill_loaded"
    SKILL_BLOCKED = "skill_blocked"
    SKILL_EXERCISED = "skill_exercised"
    SKILL_REGRESSION = "skill_regression"
    SKILL_DECAY = "skill_decay"
    SKILL_ACQUIRED = "skill_acquired"

    # Limited duty (AD-628g)
    LIMDU_RECOMMENDED = "limdu_recommended"

    # Dream / system mode
===END REPLACE===
```

`SKILL_LOADED` and `SKILL_BLOCKED` are reserved for the augmentation-injection-pipeline emitter (AD-625/626/627 territory) — they ship in this enum so consumers compile, but the emission sites for those two are out-of-scope for v1 (the augmentation injector lives in the standing-orders processor; emission wiring there is AD-628a-followup territory). The four telemetry events with active emission sites in v1 are `SKILL_EXERCISED`, `SKILL_REGRESSION`, `SKILL_DECAY`, `SKILL_ACQUIRED`.

---

## Section 1: AD-628a — Skill telemetry events

Add `set_event_emitter` setter and emission to the four `AgentSkillService` mutation methods at `src/probos/skill_framework.py`.

### Setter

Add after the `__init__` block of `AgentSkillService` (line 589 onward; verify with `Select-String -Path src\probos\skill_framework.py -Pattern "class AgentSkillService"`).

```
===MODIFY: src/probos/skill_framework.py===
===SEARCH===
    def __init__(self, db_path: str | None = None, registry: SkillRegistry | None = None,
===REPLACE===
    def set_event_emitter(self, emitter: "Callable[[Any, dict[str, Any]], None] | None") -> None:
        """Register an event emitter for skill telemetry (AD-628a).

        The emitter is called with ``(EventType, payload_dict)`` on each
        mutation. Tier-2 log-and-degrade — emitter exceptions are caught
        and logged at warning level. Pass ``None`` to unregister.
        """
        self._event_emitter = emitter

    def __init__(self, db_path: str | None = None, registry: SkillRegistry | None = None,
===END REPLACE===
```

Initialize `self._event_emitter: Callable | None = None` inside the existing `__init__` body. Use the precedent at `recreation/preferences.py:30` (`GamePreferenceTracker._emit_event_fn`).

### Emission helper (private)

Add a private helper inside `AgentSkillService`:

```python
def _emit(self, event_type: "EventType", payload: dict[str, Any]) -> None:
    if self._event_emitter is None:
        return
    try:
        self._event_emitter(event_type, payload)
    except Exception:
        logger.warning("AD-628a: skill telemetry emit failed for %s", event_type, exc_info=True)
```

(Import `EventType` from `probos.events` at the top of the file. The `Callable` type-hint requires `from typing import Callable` if not already present — verify.)

### Emission sites

After successful return from each of the four mutation methods, before the final `return` statement:

| Method | Line (verify with grep) | EventType | Payload |
|---|---|---|---|
| `acquire_skill` | `:624` | `SKILL_ACQUIRED` | `{agent_id, skill_id, to_level: record.proficiency.value, source: acquisition_source, timestamp: time.time(), reason: "acquired"}` |
| `update_proficiency` | `:689` | `SKILL_REGRESSION` if `to_level < from_level` else `SKILL_EXERCISED` | `{agent_id, skill_id, from_level: from_level.value, to_level: to_level.value, source, timestamp: time.time(), reason}` |
| `record_exercise` | `:712` | `SKILL_EXERCISED` | `{agent_id, skill_id, to_level: record.proficiency.value, source: "exercise", timestamp: time.time(), reason: "recorded_exercise"}` |
| `check_decay` | `:722` | `SKILL_DECAY` (one emit per decayed record in the returned list) | `{agent_id, skill_id, from_level, to_level, source: "decay", timestamp: time.time(), reason: "idle_decay"}` |

### Tests (`tests/test_ad628_crew_skill_readiness.py::TestSkillTelemetryEvents`)

10 tests:
1. `set_event_emitter` registers + clears (None resets)
2. `acquire_skill` fires `SKILL_ACQUIRED` with correct payload
3. `update_proficiency` upward fires `SKILL_EXERCISED` with `from_level < to_level`
4. `update_proficiency` downward fires `SKILL_REGRESSION` with `to_level < from_level`
5. `record_exercise` fires `SKILL_EXERCISED`
6. `check_decay` fires one `SKILL_DECAY` per decayed record
7. Emitter exception is caught + logged + does NOT propagate (tier-2 log-and-degrade)
8. No emitter registered → no exception, no payload generated
9. Payload `timestamp` field is a finite float
10. Payload `agent_id` and `skill_id` match the call arguments byte-for-byte

---

## Section 2: AD-628b — Agent skill readiness profile

New module `src/probos/cognitive/skill_readiness.py`. Pure read-side aggregator — depends on `AgentSkillService` + `qual_skill_bridge.SkillAdvancement` and (optionally) a regression-event ring populated by AD-628a.

### Dataclasses

```python
@dataclass(frozen=True)
class SkillRegressionEvent:
    agent_id: str
    skill_id: str
    from_level: int
    to_level: int
    timestamp: float
    reason: str = ""

@dataclass(frozen=True)
class AgentSkillReadinessProfile:
    agent_id: str
    qualifications: list[str]                  # skill_ids at APPLY+ (proficiency >= 3)
    proficiency_distribution: dict[str, int]   # ProficiencyLevel.name -> count
    recent_advancements: list["SkillAdvancement"]  # last 10 from qual_skill_bridge
    recent_regressions: list[SkillRegressionEvent]  # last 10 from internal ring
    last_exercised_per_skill: dict[str, float]
    composite_capabilities: list[str]          # composites the agent currently fires
```

### Service

```python
class AgentSkillReadinessService:
    def __init__(self, skill_service: "AgentSkillService", *, advancement_log: list["SkillAdvancement"] | None = None) -> None:
        self._skill_service = skill_service
        self._advancement_log = advancement_log if advancement_log is not None else []
        self._regression_ring: list[SkillRegressionEvent] = []  # cap at 100

    def record_regression(self, event: SkillRegressionEvent) -> None:
        """Called by the AD-628a SKILL_REGRESSION emission consumer."""

    def record_advancement(self, advancement: "SkillAdvancement") -> None:
        """Called by qual_skill_bridge integration."""

    def get_profile(self, agent_id: str) -> AgentSkillReadinessProfile:
        """Build the read-only profile for one agent."""
```

`get_profile` reads:
- `self._skill_service.get_profile(agent_id)` returns the existing `SkillProfile` (already shipped at `skill_framework.py:189`).
- `qualifications` = `[r.skill_id for r in profile.all_skills() if r.proficiency.value >= ProficiencyLevel.APPLY.value]`
- `proficiency_distribution` = counter over `r.proficiency.name` for r in `profile.all_skills()`
- `recent_advancements` = last 10 from `self._advancement_log` filtered by `agent_id`
- `recent_regressions` = last 10 from `self._regression_ring` filtered by `agent_id`
- `last_exercised_per_skill` = `{r.skill_id: r.last_exercised for r in profile.all_skills()}`
- `composite_capabilities` = uses existing `profile.has_composite_capability(skill_id)` (shipped at AD-428b W75) — iterate over registry composites.

### Tests (`TestSkillReadinessProfile`)

8 tests:
1. `get_profile` returns empty profile for unknown agent
2. `qualifications` includes only APPLY+ skills
3. `proficiency_distribution` counts levels correctly
4. `recent_advancements` capped at 10, sorted newest-first
5. `recent_regressions` capped at 10, sorted newest-first
6. `record_regression` adds to ring; ring caps at 100
7. `last_exercised_per_skill` reflects framework state
8. `composite_capabilities` lists composites the agent currently fires

---

## Section 3: AD-628c — Training Officer crew profile

### New file: `config/standing_orders/crew_profiles/training_officer.yaml`

Mirror the `counselor.yaml` shape verbatim. Required top-level fields (read `config/standing_orders/crew_profiles/counselor.yaml` for the exact schema):

```yaml
display_name: "Training Officer"
callsign: "Tucker"
department: "operations"
role: "officer"
personality:
  openness: 0.7
  conscientiousness: 0.85
  extraversion: 0.6
  agreeableness: 0.65
  neuroticism: 0.3
standing_orders:
  - "Track qualification readiness across the crew via Skill Framework + Qualification Registry."
  - "Schedule drills via DrillCalendar; surface due drills during your proactive cycle."
  - "Coordinate new-agent onboarding mentorship: announce TRAINO presence to each newly-named crew member."
  - "Generate ship-wide and per-department readiness reports on request."
  - "Recommend limited duty (LIMDU) jointly with Medical when an agent shows skill regression in cognitive RED/CRITICAL zone."
  - "Authority over qualification scheduling, drill calendar, onboarding mentorship, readiness reporting, and joint-LIMDU recommendation."
  - "NOT authority over fitness-for-duty determination (Medical owns FFFD), behavioral observation (Counselor owns COSC), or department-level CDB advancement (Department Chiefs)."
```

(Builder: read the existing `counselor.yaml` file and mirror any additional standard fields — e.g., `tier: crew`, `clearance: ENHANCED` — that the existing 14 profiles share.)

### Modify: `config/ontology/organization.yaml`

Two changes:

**(a) Add `chief_training` post under Operations.** SEARCH/REPLACE anchor on the `chief_operations` post block (verified at `:312`–`:325` via the prior grep):

```
===MODIFY: config/ontology/organization.yaml===
===SEARCH===
  # Operations
  - id: chief_operations
    title: "Chief of Operations"
    department: operations
    reports_to: first_officer
    authority_over: []
    tier: crew
    clearance: FULL
    capabilities:
      - id: ops_status
        summary: "Analyze resource utilization, capacity, and operational readiness"
      - id: ops_coordinate
        summary: "Coordinate cross-department activities and task optimization"
    does_not_have:
      - "direct system control or infrastructure management (Ship's Computer manages infrastructure)"
      - "external communications or networking equipment"
===REPLACE===
  # Operations
  - id: chief_operations
    title: "Chief of Operations"
    department: operations
    reports_to: first_officer
    authority_over: []
    tier: crew
    clearance: FULL
    capabilities:
      - id: ops_status
        summary: "Analyze resource utilization, capacity, and operational readiness"
      - id: ops_coordinate
        summary: "Coordinate cross-department activities and task optimization"
    does_not_have:
      - "direct system control or infrastructure management (Ship's Computer manages infrastructure)"
      - "external communications or networking equipment"

  - id: chief_training
    title: "Training Officer"
    department: operations
    reports_to: chief_operations
    authority_over: []
    tier: crew
    clearance: ENHANCED
    capabilities:
      - id: training_schedule
        summary: "Schedule qualification drills via DrillCalendar (AD-628d)"
      - id: training_readiness
        summary: "Compute ship-wide and per-department skill readiness reports (AD-628f)"
      - id: training_onboarding
        summary: "Mentor newly-named crew agents through the AD-515 onboarding mentorship hook (AD-628e)"
      - id: training_limdu
        summary: "Joint-author LIMDU recommendations with Medical (AD-628g)"
    does_not_have:
      - "fitness-for-duty determination (Medical owns FFFD)"
      - "behavioral observation (Counselor owns COSC)"
      - "department-level career development board advancement (Department Chiefs)"
===END REPLACE===
```

**(b) Add `training_officer` assignment.** SEARCH/REPLACE anchor on the existing `research_specialist` block (the last assignment in the file per the prior `:381`–`:386` read):

```
===SEARCH===
  - agent_type: research_specialist
    post_id: research_specialist_officer
    callsign: "Brahms"
    watches: [alpha]
===REPLACE===
  - agent_type: research_specialist
    post_id: research_specialist_officer
    callsign: "Brahms"
    watches: [alpha]
  - agent_type: training_officer
    post_id: chief_training
    callsign: "Tucker"
    watches: [alpha, beta]
===END REPLACE===
```

### Tests (`TestTrainingOfficerCrewProfile`)

6 tests:
1. `training_officer.yaml` exists and parses as YAML with required keys
2. `callsign == "Tucker"`, `department == "operations"`, `role == "officer"`
3. `organization.yaml` parses with `chief_training` post present, `tier == "crew"`
4. `organization.yaml` parses with `training_officer / Tucker` assignment present, `watches == ["alpha", "beta"]`
5. No callsign collision with existing 14 assignments — `Tucker` does not appear elsewhere
6. `chief_training.reports_to == "chief_operations"`

---

## Section 4: AD-628d — Drill calendar

New module `src/probos/cognitive/drill_calendar.py`.

### Dataclasses

```python
@dataclass(frozen=True)
class DrillEntry:
    drill_id: str
    agent_id: str
    qualification_test: str
    scheduled_at: float
    status: Literal["scheduled", "executed", "missed"]
    result: "TestResult | None" = None  # TestResult from cognitive.qualification
```

### Service

```python
class DrillCalendar:
    def __init__(self, qualification_harness: "QualificationHarness") -> None:
        self._harness = qualification_harness
        self._drills: dict[str, DrillEntry] = {}
        self._next_id = 0

    def schedule_drill(self, agent_id: str, qualification_test: str, scheduled_at: float) -> str:
        """Schedule a drill. Returns drill_id.

        Raises ``KeyError`` if ``qualification_test`` is not registered with
        the QualificationHarness — per W93-3 hard-stop, drill creation
        validates the test name and refuses to schedule unknown tests.
        """

    def list_due_drills(self, *, before: float) -> list[DrillEntry]:
        """List all SCHEDULED drills with scheduled_at <= before."""

    async def execute_drill(self, drill_id: str) -> DrillEntry:
        """Execute the drill via QualificationHarness.run_test.

        Calls ``self._harness.run_test(entry.qualification_test, entry.agent_id)``,
        records the TestResult on the entry, sets status="executed", and
        returns the updated entry. The qual_skill_bridge → SKILL_EXERCISED
        chain fires automatically through existing infrastructure.
        """

    def mark_missed(self, drill_id: str) -> DrillEntry:
        """Mark a drill as missed (status='missed')."""

    def get_drill(self, drill_id: str) -> DrillEntry | None: ...

    def list_drills_for_agent(self, agent_id: str) -> list[DrillEntry]: ...
```

### Validation: qualification test must be registered

Inside `schedule_drill`:

```python
if qualification_test not in self._harness.registered_tests():
    raise KeyError(
        f"AD-628d: qualification_test {qualification_test!r} not registered "
        f"with QualificationHarness; cannot schedule drill"
    )
```

The canonical registry-check method is `QualificationHarness.registered_tests() -> dict[str, QualificationTest]` at `cognitive/qualification.py:376`. The `register_test` method at `:371` is the inverse (writer side) used by tests to populate the harness with fixtures.

### Tests (`TestDrillCalendar`)

10 tests:
1. `schedule_drill` returns a drill_id and stores the entry
2. `schedule_drill` raises `KeyError` for unknown qualification_test (W93-3)
3. `list_due_drills` returns only SCHEDULED drills with `scheduled_at <= before`
4. `list_due_drills` excludes EXECUTED and MISSED drills
5. `execute_drill` calls `QualificationHarness.run_test` with correct args
6. `execute_drill` records `result` on the entry and sets `status="executed"`
7. `mark_missed` sets `status="missed"`
8. `get_drill` returns None for unknown drill_id
9. `list_drills_for_agent` filters correctly
10. drill_id values are unique across multiple schedules

---

## Section 5: AD-628e — Onboarding mentor announcer

Modify `src/probos/agent_onboarding.py`. Add the announcer setter and invocation. **The class is named `AgentOnboardingService` at `:39`** (verified by `Select-String -Path src\probos\agent_onboarding.py -Pattern "^class"` returning `class AgentOnboardingService:`).

### Setter

Add to `AgentOnboardingService` class (constructor at `:39`+):

```python
def register_mentor_announcer(
    self,
    announcer: "Callable[[str, str], Awaitable[None]] | None",
) -> None:
    """Register a TRAINO mentor announcer (AD-628e).

    The announcer is called as ``await announcer(new_agent_callsign, post_id)``
    just before the AD-499 self-naming event-log block at :233.
    Tier-2 log-and-degrade — exceptions are caught and logged at warning.
    Pass ``None`` to unregister.
    """
    self._mentor_announcer = announcer
```

Initialize `self._mentor_announcer: Callable | None = None` inside `__init__`.

### Invocation block

At the AD-499 block at `agent_onboarding.py:233` (verified anchor `# AD-499: emit self-naming event`), insert the announcer call **before** the existing `if self._event_log:` line:

```
===MODIFY: src/probos/agent_onboarding.py===
===SEARCH===
                        # AD-499: emit self-naming event
                        if self._event_log:
===REPLACE===
                        # AD-628e: TRAINO mentor announcement (post-naming-ceremony)
                        if self._mentor_announcer is not None and asyncio.iscoroutinefunction(self._mentor_announcer):
                            try:
                                await self._mentor_announcer(agent.callsign, getattr(agent, "post_id", ""))
                            except Exception:
                                logger.warning(
                                    "AD-628e: mentor announcer failed for %s",
                                    agent.callsign,
                                    exc_info=True,
                                )

                        # AD-499: emit self-naming event
                        if self._event_log:
===END REPLACE===
```

Builder: verify the exact SEARCH context (the AD-499 block) is unique in the file. The literal `# AD-499: emit self-naming event` anchor was confirmed unique at `:233` via the prior grep. The `getattr(agent, "post_id", "")` pattern handles agents without a `post_id` attribute defensively.

### Tests (`TestOnboardingMentorAnnouncer`)

6 tests:
1. `register_mentor_announcer(None)` clears any prior registration
2. With announcer registered, post-naming-ceremony invokes `await announcer(callsign, post_id)`
3. Without announcer registered, naming-ceremony completes without exception
4. Announcer that raises is caught + logged + does NOT propagate (tier-2)
5. Synchronous (non-coroutine) announcer is rejected by `iscoroutinefunction` guard — silently skipped per BF-254 pattern
6. Announcer receives the FINAL callsign (post-rename) not the ceremonial intermediate name

---

## Section 6: AD-628f — Readiness reporter

New module `src/probos/cognitive/readiness_reporter.py`.

### Dataclasses

```python
@dataclass(frozen=True)
class DepartmentReadinessReport:
    department: str
    member_count: int
    qualified_skill_coverage: float    # mean across crew of |qualifications|/|expected_skills_for_post|
    proficiency_mean: float            # mean ProficiencyLevel.value across all skill records
    regression_count_24h: int
    decay_count_24h: int

@dataclass(frozen=True)
class ShipReadinessReport:
    captured_at: float
    departments: list[DepartmentReadinessReport]
    composite_score: float             # 0.0-1.0 weighted mean across departments by member_count
    c_rating: Literal["C1", "C2", "C3", "C4"]
```

### C-rating mapping

```python
def _to_c_rating(score: float) -> str:
    if score >= 0.85:
        return "C1"
    if score >= 0.70:
        return "C2"
    if score >= 0.50:
        return "C3"
    return "C4"
```

### Service

```python
class ReadinessReporter:
    def __init__(
        self,
        readiness_service: AgentSkillReadinessService,
        ontology: "Ontology",       # existing AD-339/AD-595c surface — verify exact import path
        spawner: "PoolSpawner",     # for list_active_agents() — verify exact name
    ) -> None: ...

    def compute_department_readiness(self, department: str) -> DepartmentReadinessReport: ...

    def compute_ship_readiness(self) -> ShipReadinessReport: ...
```

`compute_department_readiness` reads the `assignments:` block from `ontology` to find agent_types whose post is in `department`, looks up active agent_ids via `spawner.list_active_agents()` filtered by `agent.agent_type == assignment.agent_type`, calls `readiness_service.get_profile(agent_id)` for each, and aggregates.

Builder: the exact ontology + spawner method names must be grep-verified before calling. If the canonical method is `runtime.spawner.pools` per the existing `runtime.py:2973` precedent (verified earlier in the prior dispatch), use that. The `expected_skills_for_post` lookup may require a new helper on the existing `SkillRegistry` — Builder, if no such helper exists, hardcode `expected_skills_for_post = list_skills_for_department(department)` returning all `domain == department` skills from the registry.

### Tests (`TestReadinessReporter`)

10 tests:
1. `compute_department_readiness` for empty department returns `member_count=0` + zero scores
2. `compute_department_readiness` for medical department aggregates correctly with 3 fixture agents
3. `qualified_skill_coverage` = mean of (qualifications count / expected count) across crew
4. `proficiency_mean` averages level values correctly
5. `regression_count_24h` counts only events within last 86400s
6. `decay_count_24h` counts only events within last 86400s
7. `compute_ship_readiness` returns one DepartmentReadinessReport per active department
8. `composite_score` is member-count-weighted mean of department scores
9. `c_rating` mapping: 0.90 → C1, 0.75 → C2, 0.55 → C3, 0.20 → C4
10. `captured_at` is a finite float close to wall-clock at call time

---

## Section 7: AD-628g — LIMDU protocol

New module `src/probos/cognitive/limdu.py`.

### Dataclasses

```python
@dataclass(frozen=True)
class LIMDURecommendation:
    recommendation_id: str
    agent_id: str
    medical_callsign: str
    traino_callsign: str
    reason: str
    cognitive_zone: "CognitiveZone"  # AD-506a
    regressed_skills: list[str]
    remediation_plan: list[DrillEntry]  # from AD-628d
    created_at: float
    status: Literal["recommended", "accepted", "completed", "expired"] = "recommended"
```

### Service

```python
class LIMDUService:
    def __init__(
        self,
        readiness_service: AgentSkillReadinessService,
        drill_calendar: DrillCalendar,
        circuit_breaker: "CircuitBreaker | None" = None,  # for cognitive_zone lookup
    ) -> None: ...

    def set_event_emitter(self, emitter: "Callable[[EventType, dict], None] | None") -> None: ...

    def recommend_limited_duty(
        self,
        agent_id: str,
        *,
        medical_callsign: str,           # required keyword-only — enforces joint authority at type level
        traino_callsign: str,            # required keyword-only — enforces joint authority at type level
        reason: str,
    ) -> LIMDURecommendation:
        """Generate a LIMDU recommendation with auto-populated remediation plan.

        Reads AD-628b profile to find regressed skills (from recent_regressions),
        reads AD-506a cognitive zone (or uses GREEN if circuit_breaker is None),
        auto-schedules a drill for each regressed skill via AD-628d
        DrillCalendar.schedule_drill (1 day from now per skill),
        emits LIMDU_RECOMMENDED event.
        """

    def get_recommendation(self, recommendation_id: str) -> LIMDURecommendation | None: ...
    def list_active_recommendations(self) -> list[LIMDURecommendation]: ...
    def update_status(self, recommendation_id: str, status: str) -> LIMDURecommendation | None: ...
```

### Joint-authority enforcement note

The two required keyword-only parameters `medical_callsign` and `traino_callsign` enforce joint authority **at the call signature level** — callers cannot omit either. This is the v1 enforcement mechanism per AD-628 DD-5. **Per-callsign role validation (e.g., asserting that `medical_callsign` actually belongs to a Medical-department agent) is NOT enforced in v1** — that is a calling-agent-level concern. The dataclass field names + required-kwargs signature are the v1 joint-authority contract.

### Auto-population of remediation plan

```python
regressed_skills = [r.skill_id for r in profile.recent_regressions]
remediation = []
for skill_id in regressed_skills:
    # Find the qualification test for this skill (Builder: verify the lookup
    # mechanism — likely qualification_registry.find_test_for_skill(skill_id)
    # or qual_skill_bridge.test_for_skill(skill_id); use whichever exists at HEAD)
    test_name = self._lookup_qualification_test(skill_id)
    if test_name is None:
        continue
    drill_id = self._drill_calendar.schedule_drill(
        agent_id=agent_id,
        qualification_test=test_name,
        scheduled_at=time.time() + 86400,  # 1 day from now
    )
    remediation.append(self._drill_calendar.get_drill(drill_id))
```

If no qualification test exists for a regressed skill, skip silently (tier-1 swallow) — the v1 LIMDU does not block on incomplete coverage.

### Tests (`TestLIMDUProtocol`)

10 tests:
1. `recommend_limited_duty` requires both `medical_callsign` AND `traino_callsign` kwargs (TypeError if either missing)
2. Returns a `LIMDURecommendation` with both callsigns present
3. `regressed_skills` populated from AD-628b profile's `recent_regressions`
4. `remediation_plan` contains one DrillEntry per regressed skill with a registered qualification test
5. Skills without registered qualification tests are skipped (no exception)
6. `cognitive_zone` defaults to `GREEN` when `circuit_breaker is None`
7. `cognitive_zone` reflects the `CircuitBreaker` zone when wired
8. `LIMDU_RECOMMENDED` event is emitted with full payload
9. `update_status` mutates a recommendation's status field
10. `list_active_recommendations` excludes status=="completed" and status=="expired"

---

## Section 8: AD-628h — `/readiness` slash command

Modify `src/probos/experience/commands/commands_status.py`. Add `cmd_readiness` next to `cmd_status` at `:16`.

```python
async def cmd_readiness(
    runtime: "ProbOSRuntime",
    console: "Console",
    args: list[str],
) -> None:
    """Render the current ship readiness report (AD-628h)."""
    reporter = getattr(runtime, "readiness_reporter", None)
    if reporter is None:
        console.print("[yellow]ReadinessReporter not wired on runtime[/yellow]")
        return
    report = reporter.compute_ship_readiness()
    table = Table(
        title=f"Ship Readiness — {report.c_rating} (composite {report.composite_score:.2f})",
        box=ROUNDED,
        expand=False,
    )
    table.add_column("Department")
    table.add_column("Members", justify="right")
    table.add_column("Coverage", justify="right")
    table.add_column("Proficiency", justify="right")
    table.add_column("Regressions 24h", justify="right")
    table.add_column("Decay 24h", justify="right")
    for dept in report.departments:
        table.add_row(
            dept.department,
            str(dept.member_count),
            f"{dept.qualified_skill_coverage:.2f}",
            f"{dept.proficiency_mean:.2f}",
            str(dept.regression_count_24h),
            str(dept.decay_count_24h),
        )
    console.print(table)
```

Imports: `from rich.table import Table`, `from rich.box import ROUNDED` — verify these are already imported in `commands_status.py` (the `cmd_status` precedent already renders Rich tables).

Also register `cmd_readiness` in the slash-command dispatcher. Builder: grep for the dispatcher table — likely in the same file or in `experience/commands/__init__.py`. The existing 8 `cmd_*` functions in `commands_status.py:16/30/44/89/100/141/153/164` are all registered through the same mechanism; mirror that.

### Tests (`TestReadinessSlashCommand`)

6 tests:
1. `cmd_readiness` with no `readiness_reporter` on runtime prints fallback message
2. `cmd_readiness` with reporter prints a Rich table with title containing the c_rating
3. Table contains one row per department in the report
4. Numeric columns format with 2 decimals
5. Empty report (no departments) produces a table with no data rows but valid header
6. Reporter exception is caught + reported + does NOT propagate

---

## Startup wiring tests (`TestStartupWiring`)

4 tests:
1. `runtime.skill_readiness_service` is wired post-startup (or `getattr(runtime, "skill_readiness_service", None) is not None`)
2. `runtime.drill_calendar` is wired post-startup
3. `runtime.readiness_reporter` is wired post-startup
4. `runtime.limdu_service` is wired post-startup

Builder: the wiring location is in `src/probos/runtime.py` startup or `src/probos/startup/` — find the closest precedent (e.g., AD-526d `recreation/preferences.py` wiring) and mirror it. The TRAINO mentor-announcer registration also lives in startup: `runtime.agent_onboarding.register_mentor_announcer(traino_announcer)` where `traino_announcer` is a coroutine that DMs the new agent via Ward Room.

---

## What This Does NOT Change

- **No modification to `AgentSkillService` mutation method signatures** (only ADD emission side effects inside the existing bodies — W93-1 hard-stop).
- **No modification to existing 14 crew profiles** in `config/standing_orders/crew_profiles/`.
- **No modification to existing 14 assignments** in `config/ontology/organization.yaml`.
- **No modification to AD-477 `QualificationHarness` or `QualificationStore`** (DrillCalendar layers ON TOP).
- **No modification to AD-515 `AgentOnboardingService` core flow** (only ADD a setter + an optional invocation block at the AD-499 anchor at `:233`).
- **No modification to AD-506a `CognitiveZone` enum** (LIMDU consumes it directly).
- **No new Pydantic config models** — TRAINO is config-only via the existing standing-orders YAML pattern.
- **No new database tables in v1** — DrillCalendar and LIMDUService use in-memory rings; durable persistence is forcing-function letter AD-628i.
- **No Holodeck primitive** — drill execution is qualification-test-only; Holodeck-scenario surface is forcing-function letter AD-628d-1.
- **No Birth-Chamber-embodied mentorship** — onboarding mentorship is DM-style announcement-only; Birth-Chamber surface is forcing-function letter AD-628e-1.
- **No automatic LIMDU enactment** (reduced-duty enforcement) — v1 records recommendations only; enactment is downstream-consumer territory.

---

## Tracking

- **`PROGRESS.md`** line 2: 12041 → 12107 (or whatever Builder ships ≥ 12107). Append a line describing AD-628 v1 closure with the eight-letter sub-AD breakdown.
- **`docs/development/roadmap.md:5543`–`:5560`**: flip `*(SCOPED, OSS)*` → `*(complete, OSS)*`; append the eight-letter v1 ship-set + the three forcing-function future-AD letters + the three commercial carve-outs descriptor.
- **`decisions-era-4-evolution.md`**: convert the existing AD-628 SCOPED entry at `:4608`–`:4651` to COMPLETE; append the implementation-section table + grep-anchored verify-first footer.
- **`prompts/wave-plan.yaml`**: append the W93 entry per the W92 precedent (id "93" + depends_on `["92"]` + dispatch_prompt + prompt_paths + issues_to_close [223] + status pending + 600-word `notes:` summary).
- **`gh issue close 223`**: with the canonical close note (Section 12 below).

---

## Section 12: Issue close note

```
Closed by Wave 93 (AD-628 v1 Crew Skill Readiness Monitoring + Training
Officer Role, +66 tests floor).

Eight sub-AD letters shipped in v1:
- 628a Skill telemetry events (SKILL_EXERCISED / SKILL_REGRESSION /
  SKILL_DECAY / SKILL_ACQUIRED emissions on AgentSkillService mutations,
  plus reserved SKILL_LOADED / SKILL_BLOCKED for the augmentation injector)
- 628b AgentSkillReadinessProfile + service over qual_skill_bridge +
  framework state
- 628c Training Officer crew profile (callsign Tucker, department
  Operations, post chief_training)
- 628d DrillCalendar layered on AD-477 QualificationHarness — drill
  scheduling without Holodeck dependency
- 628e Onboarding mentor-announcer hook into AD-515 AgentOnboardingService
  post-naming-ceremony block
- 628f ReadinessReporter with DepartmentReadinessReport +
  ShipReadinessReport + C-rating mapping
- 628g LIMDUService with joint-authority required keyword-only parameters
  + auto-populated remediation plan via DrillCalendar
- 628h `/readiness` slash command surfacing ShipReadinessReport

Three future sub-AD letters parked with explicit forcing functions:
AD-628d-1 Holodeck Scenario Selection (forcing function: AD-486 +
AD-539b ship Holodeck primitive); AD-628e-1 Birth Chamber Mentor
Embodiment (forcing function: AD-486 ships Birth Chamber); AD-628i
Durable persistence (forcing function: 30 days of in-memory operation
or hosted-deployment opt-in).

Three commercial-repo carve-outs noted (NOT v1 deferrals — wrong-repo
by roadmap design): fleet-wide cross-ship readiness rollup,
customer-facing PQS-board examination service, outcome-style
readiness-improvement consulting overlay.
```

---

## Acceptance Criteria

1. All eight implementation sections build without phantom-API or layer-discipline errors.
2. New tests at `tests/test_ad628_crew_skill_readiness.py` pass at +66 floor (target ≥ 12107 vs baseline 12041).
3. Existing tests at `tests/test_ad428b_skill_advanced.py` (18 tests) and `tests/test_ad429e_dict_migration.py` continue to pass without modification (W93-1 hard-stop).
4. Banned-pattern audit on shipped artifacts + commit messages returns zero hits per pattern.
5. Tracker updates apply cleanly: PROGRESS line 2, roadmap.md AD-628 entry, decisions-era-4 AD-628 entry, wave-plan.yaml W93 entry.
6. `gh issue close 223` succeeds with the canonical close note.
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-05-07, HEAD `c6c38ec`)

```
Select-String -Path src/probos/skill_framework.py -Pattern "async def acquire_skill|async def update_proficiency|async def record_exercise|async def check_decay"
  624:    async def acquire_skill(
  689:    async def update_proficiency(
  712:    async def record_exercise(self, agent_id: str, skill_id: str) -> None:
  722:    async def check_decay(self, now: float | None = None) -> list[A...

Select-String -Path src/probos/cognitive/qual_skill_bridge.py -Pattern "class SkillAdvancement"
  21: class SkillAdvancement:

Select-String -Path src/probos/cognitive/qualification.py -Pattern "^class "
  39: class QualificationTest(Protocol):
  71: class TestResult:
  87: class ComparisonResult:
  136: class QualificationStore:
  350: class QualificationHarness:

Select-String -Path src/probos/cognitive/qualification.py -Pattern "def register_test|def registered_tests|async def run_test"
  371:    def register_test(self, test: QualificationTest) -> None:
  376:    def registered_tests(self) -> dict[str, QualificationTest]:
  380:    async def run_test(

Select-String -Path src/probos/agent_onboarding.py -Pattern "^class|# AD-499: emit self-naming event"
  39: class AgentOnboardingService:
  233:                        # AD-499: emit self-naming event   (search anchor for AD-628e insertion)

Select-String -Path src/probos/cognitive/circuit_breaker.py -Pattern "class CognitiveZone"
  42: class CognitiveZone(Enum):

Select-String -Path src/probos/events.py -Pattern "class EventType|WARD_ROOM_ENDORSEMENT"
  20: class EventType(str, Enum):
  67:     WARD_ROOM_ENDORSEMENT = "ward_room_endorsement"

Select-String -Path src/probos/events.py -Pattern "SKILL_(LOADED|BLOCKED|EXERCISED|REGRESSION|DECAY|ACQUIRED)|LIMDU_RECOMMENDED"
  (zero matches — collision-free)

Select-String -Path src/probos/**/*.py -Pattern "[Hh]olodeck|BirthChamber|birth_chamber"
  src/probos/crew_development/boot_camp.py:4    "no Holodeck integration"  (deferral comment)
  src/probos/recreation/preferences.py:5        "AD-526f holodeck integration" (deferral comment)
  src/probos/security/autonomy_boundaries.py:10 "Holodeck training is AD-511c" (deferral comment)
  src/probos/crew_development/curriculum.py:4   "AD-486 onboarding Phase 1" (deferral comment)
  (zero implementation hits — confirms AD-486 + AD-539b substrate gap; forcing-function letters AD-628d-1 + AD-628e-1 justified)

Select-String -Path config/standing_orders/crew_profiles -Pattern "callsign:" -Recurse
  14 callsign entries across 14 YAML files (existing crew-profile schema authority)

Select-String -Path config/ontology/organization.yaml -Pattern "^  - id: chief_|^  - agent_type:" -CaseSensitive
  posts at :25-:325 (chief_*, etc.); assignments at :326-:386 (14 agent_type entries; insertion point for Tucker is post research_specialist at :381-:385)

Select-String -Path src/probos/experience/commands/commands_status.py -Pattern "^async def cmd_"
  16: async def cmd_status
  30: async def cmd_agents
  44: async def cmd_ping
  89: async def cmd_scaling
  100: async def cmd_federation
  141: async def cmd_peers
  153: async def cmd_credentials
  164: async def cmd_debug
  (precedent for cmd_readiness placement)

Highest AD: 696 (PROGRESS.md / DECISIONS.md / decisions-era-*.md / docs/development/roadmap.md max)
Highest BF: 596 (no BF minted by W93)
```

All extension points exist at HEAD. No phantom APIs introduced by this prompt. Forcing functions (AD-628d-1 / AD-628e-1 / AD-628i) point at substrate that is genuinely absent at HEAD per grep evidence above.
