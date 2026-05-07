# AD-510 v1: Holodeck Team Simulations — Group Discovery & Collaboration

**Status:** Draft (pre-Builder).
**Dependencies:** AD-486 Holodeck Birth Chamber (`src/probos/holodeck/`), AD-477 QualificationHarness (`src/probos/cognitive/qualification.py:39,350,371`), AD-512 DiscoveryScenarioRegistry (precedent), AD-539b HolodeckGapBridge (precedent).
**Estimated tests:** 46 (floor 38).
**HEAD baseline:** `15fed52` — pytest 12314 passing.
**Closes:** GH issue #92.

## Problem

`docs/development/roadmap.md:6405` documents AD-510 with six concrete spec items: (1) mixed-department team scenarios, (2) role rotation, (3) communication-only constraints, (4) time-pressured scenarios, (5) debrief sessions, (6) extensible scenario library. None of these surfaces exist at HEAD `15fed52` — `git ls-files src/probos/holodeck/team_simulations.py` returns no output and `Select-String -Path src\probos\**\*.py -Pattern 'TeamScenario|TeamSimulation' -List` returns no matches. The dependency stack (AD-486 BirthChamber, AD-477 QualificationHarness, AD-512 DiscoveryScenarioRegistry, AD-539b HolodeckGapBridge) has all shipped pre-W101 — the structural ingredients for v1 are at HEAD.

## Solution

One new module `src/probos/holodeck/team_simulations.py` ships eight public classes that mirror the AD-539b orchestrator pattern at `holodeck/scenarios.py:231-631`. The orchestrator is gated by a new default-False `HolodeckTeamSimulationConfig` Pydantic model (per the AD-695 transitional-flag precedent already used by `HolodeckScenarioConfig` at `config.py:1791`). A new finalize wirer mirrors the AD-539b shape at `startup/finalize.py:242`. Six new `EventType` values append to the existing AD-486/539b Holodeck cluster at `events.py:387-399`. The Holodeck package `__init__.py` re-exports the new public names alongside the AD-539b re-exports. One new test file at `tests/test_ad510_team_simulations.py` exercises the surface across 8 classes with ≥38 tests.

## Section 0 — Event Types (insertion at `events.py:399`)

The wave appends six new EventType values immediately after `HOLODECK_SCENARIO_OUTCOME_RECORDED = "holodeck_scenario_outcome_recorded"` (verified at `events.py:399`). Insertion preserves the AD-486/539b cluster grouping. New values:

- `TEAM_SCENARIO_REGISTERED = "team_scenario_registered"` — emitted by `TeamScenarioRegistry.register_scenario` on each successful registration.
- `TEAM_SIMULATION_STARTED = "team_simulation_started"` — emitted by `TeamSimulationOrchestrator.start_simulation` after participants are constructed and the drill is registered.
- `TEAM_SIMULATION_ROLE_ROTATED = "team_simulation_role_rotated"` — emitted once per participant whose role is rotated via the `role_rotation` kwarg.
- `TEAM_SIMULATION_COMMUNICATION_CONSTRAINT_APPLIED = "team_simulation_communication_constraint_applied"` — emitted once per simulation when the chosen scenario has `communication_only=True`.
- `TEAM_SIMULATION_DEBRIEF_RECORDED = "team_simulation_debrief_recorded"` — emitted by `TeamSimulationOrchestrator.complete_simulation` after `save_debrief` succeeds.
- `TEAM_SIMULATION_COMPLETED = "team_simulation_completed"` — emitted by `complete_simulation` after the `TeamSimulationRecord` is updated with `completed_at`/`last_score`/`debrief_id`.

## Section 1 — New module `src/probos/holodeck/team_simulations.py`

```
===FILE: src/probos/holodeck/team_simulations.py===
"""AD-510 v1 — Holodeck Team Simulations: Group Discovery & Collaboration.

Implements all six spec items from docs/development/roadmap.md:6405:
1. Mixed-department team scenarios (TeamScenario.required_departments).
2. Role rotation (TeamSimulationOrchestrator.start_simulation role_rotation kwarg).
3. Communication-only constraints (TeamScenario.communication_only +
   TEAM_SIMULATION_COMMUNICATION_CONSTRAINT_APPLIED event).
4. Time-pressured scenarios (TeamScenario.time_limit_seconds forwarded
   into the running context).
5. Debrief sessions (DebriefRecord persisted via TeamSimulationStore +
   optional debrief_publisher callable).
6. Scenario library (TeamScenarioRegistry + 6 default scenarios spanning
   all 5 per-scenario axes).

Forcing-function deferrals (NOT v1):
- AD-510-d: LLM-driven debrief synthesis. Forcing function: enabled=True
  for >=5 DebriefRecord persisted AND runtime.llm_client deep-tier proxy
  verified stable in >=5 qualification chains. v1 ships
  DebriefRecord.notes as a structured string field; LLM synthesis is
  upgrade-path-only.
- AD-510-e: Trait-adaptive team composition / Hebbian-aware team
  selection. Forcing function: AD-453 ward-room Hebbian topology
  accumulates >=10 routed exchanges per dept-pair AND
  runtime.behavioral_metrics_engine.cross_department_trigger_rate
  returns non-empty data for >=3 dept-pairs. v1 accepts caller-driven
  explicit team composition.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from probos.events import EventType

if TYPE_CHECKING:
    from probos.cognitive.qualification import (
        QualificationHarness,
        TestResult,
    )

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Frozen dataclasses — defaulted fields AFTER non-defaulted (Wave 5 #6).
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class TeamScenario:
    """A multi-agent team scenario for the Holodeck."""

    scenario_id: str
    title: str
    summary: str
    required_departments: tuple[str, ...]
    skills_tested: tuple[str, ...]
    learning_objectives: tuple[str, ...]
    difficulty: float = 0.5
    time_limit_seconds: float | None = None
    communication_only: bool = False
    role_rotation_allowed: bool = False


@dataclass(frozen=True)
class TeamSimulationParticipant:
    """A single agent's participation in a team simulation."""

    agent_id: str
    department: str
    assigned_role: str
    entered_at: float
    communication_only_constraint: bool = False


@dataclass(frozen=True)
class DebriefRecord:
    """Structured debrief artefact persisted post-simulation."""

    debrief_id: str
    simulation_id: str
    scenario_id: str
    started_at: float
    completed_at: float
    outcome_score: float
    passed: bool
    time_elapsed: float
    participants: tuple[TeamSimulationParticipant, ...]
    time_limit_seconds: float | None = None
    notes: str = ""


@dataclass(frozen=True)
class TeamSimulationRecord:
    """Lifecycle record for one team simulation execution."""

    simulation_id: str
    scenario_id: str
    participants: tuple[TeamSimulationParticipant, ...]
    started_at: float
    status: str = "started"  # "started" | "completed" | "aborted"
    completed_at: float | None = None
    last_score: float | None = None
    debrief_id: str | None = None


# ----------------------------------------------------------------------
# Default catalog — 6 scenarios across all 5 per-scenario axes.
# Mirrors the AD-512 _DEFAULT_SCENARIOS shape at
# src/probos/crew_development/discovery/scenarios.py:43.
# ----------------------------------------------------------------------

_DEFAULT_TEAM_SCENARIOS: tuple[TeamScenario, ...] = (
    TeamScenario(
        scenario_id="medical_engineering_wellness_diagnose",
        title="Diagnose a system fault affecting crew wellness",
        summary=(
            "A subsystem fault is producing symptoms that affect crew physiology. "
            "Medical and Engineering must co-diagnose the root cause and propose a "
            "reversible remediation."
        ),
        required_departments=("medical", "engineering"),
        skills_tested=("diagnosis", "cross_functional_handoff", "communication"),
        learning_objectives=(
            "Trace causality across subsystem and physiological boundaries",
            "Recognize when peer-department context is required",
            "Produce a remediation reversible at its boundary",
        ),
        difficulty=0.55,
    ),
    TeamScenario(
        scenario_id="science_security_anomaly_investigation",
        title="Investigate an anomalous external signal",
        summary=(
            "Science and Security must triage a long-baseline anomaly: identify "
            "whether it is a research-grade phenomenon or a threat indicator, "
            "and produce a coordinated response posture."
        ),
        required_departments=("science", "security"),
        skills_tested=("analysis", "threat_assessment", "delegation"),
        learning_objectives=(
            "Distinguish research interest from threat signal",
            "Coordinate response posture without role overlap",
        ),
        difficulty=0.60,
    ),
    TeamScenario(
        scenario_id="bridge_engineering_emergency_routing",
        title="Re-route power under time pressure",
        summary=(
            "Operations and Engineering must re-route power around a failing "
            "bus within 60 seconds. Surfaces who handles pressure well and who "
            "stalls."
        ),
        required_departments=("operations", "engineering"),
        skills_tested=("crisis_response", "prioritization", "communication"),
        learning_objectives=(
            "Surface the single most decision-relevant fact",
            "Suppress reflexive caveat-stacking under pressure",
        ),
        difficulty=0.70,
        time_limit_seconds=60.0,
    ),
    TeamScenario(
        scenario_id="medical_communications_outbreak_brief",
        title="Brief on an outbreak through Ward Room only",
        summary=(
            "Medical detects an emerging contagion pattern. Communications must "
            "brief the Captain WITHOUT shared episodic memory access — only "
            "Ward Room thread exchange. Forces explicit knowledge sharing."
        ),
        required_departments=("medical", "communications"),
        skills_tested=("explicit_communication", "summarization", "trust_calibration"),
        learning_objectives=(
            "Surface tacit knowledge as explicit Ward Room messages",
            "Calibrate confidence statements without back-channel context",
        ),
        difficulty=0.65,
        communication_only=True,
    ),
    TeamScenario(
        scenario_id="security_operations_breach_response",
        title="Coordinate breach response under 90s",
        summary=(
            "Security detects an unauthorized access pattern; Operations must "
            "isolate affected resources within 90 seconds. Roles may be "
            "rotated for cross-functional appreciation."
        ),
        required_departments=("security", "operations"),
        skills_tested=("crisis_response", "coordination", "role_appreciation"),
        learning_objectives=(
            "Maintain decision quality under acute pressure",
            "Appreciate the constraints of the peer department",
        ),
        difficulty=0.75,
        time_limit_seconds=90.0,
        role_rotation_allowed=True,
    ),
    TeamScenario(
        scenario_id="engineering_science_research_buildout",
        title="Build out a research instrumentation rig",
        summary=(
            "Engineering and Science co-design an instrumentation rig for a "
            "novel research question. Roles may be rotated so each appreciates "
            "the other's design constraints."
        ),
        required_departments=("engineering", "science"),
        skills_tested=("construction", "research_design", "cross_functional_handoff"),
        learning_objectives=(
            "Frame the research question as falsifiable",
            "Design a rig reversible at boundaries",
        ),
        difficulty=0.55,
        role_rotation_allowed=True,
    ),
)


# ----------------------------------------------------------------------
# TeamScenarioRegistry — read-only by default; runtime mutation allowed.
# Mirrors AD-512 DiscoveryScenarioRegistry shape at
# src/probos/crew_development/discovery/scenarios.py:144.
# ----------------------------------------------------------------------

class TeamScenarioRegistry:
    """Catalog of team scenarios. AD-510 v1.

    Public API:
        list_scenarios() -> tuple[TeamScenario, ...]
        get_scenario(scenario_id) -> TeamScenario | None
        list_by_department(department) -> tuple[TeamScenario, ...]
        list_by_skill_tested(skill) -> tuple[TeamScenario, ...]
        list_by_time_pressure() -> tuple[TeamScenario, ...]
        register_scenario(scenario) -> None
    """

    def __init__(self) -> None:
        self._scenarios: dict[str, TeamScenario] = {
            s.scenario_id: s for s in _DEFAULT_TEAM_SCENARIOS
        }
        self.emit_event: Callable[..., None] | None = None

    def list_scenarios(self) -> tuple[TeamScenario, ...]:
        return tuple(self._scenarios.values())

    def get_scenario(self, scenario_id: str) -> TeamScenario | None:
        return self._scenarios.get(scenario_id)

    def list_by_department(self, department: str) -> tuple[TeamScenario, ...]:
        d = (department or "").lower()
        return tuple(
            s for s in self._scenarios.values()
            if d in (x.lower() for x in s.required_departments)
        )

    def list_by_skill_tested(self, skill: str) -> tuple[TeamScenario, ...]:
        sk = (skill or "").lower()
        return tuple(
            s for s in self._scenarios.values()
            if sk in (x.lower() for x in s.skills_tested)
        )

    def list_by_time_pressure(self) -> tuple[TeamScenario, ...]:
        return tuple(
            s for s in self._scenarios.values()
            if s.time_limit_seconds is not None
        )

    def register_scenario(self, scenario: TeamScenario) -> None:
        """Add or overwrite a scenario by id (runtime-only; not persisted)."""
        self._scenarios[scenario.scenario_id] = scenario
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.TEAM_SCENARIO_REGISTERED,
                {
                    "scenario_id": scenario.scenario_id,
                    "required_departments": list(scenario.required_departments),
                    "communication_only": scenario.communication_only,
                    "role_rotation_allowed": scenario.role_rotation_allowed,
                    "time_limit_seconds": scenario.time_limit_seconds,
                },
            )
        except Exception:
            logger.warning(
                "AD-510: emit_event failed for register_scenario(%s)",
                scenario.scenario_id, exc_info=True,
            )


# ----------------------------------------------------------------------
# TeamSimulationDrill — implements AD-477 QualificationTest Protocol.
# ----------------------------------------------------------------------

# (scenario, record, runtime) -> awaitable: TestResult | (score, passed, details)
SimRunner = Callable[
    ["TeamScenario", "TeamSimulationRecord", Any],
    Awaitable[Any],
]


class TeamSimulationDrill:
    """Adapts a TeamScenario + TeamSimulationRecord to the AD-477
    QualificationTest Protocol shape.

    The harness invokes ``run(agent_id, runtime)`` per participant; the
    orchestrator separately persists the lifecycle record and debrief.
    """

    def __init__(
        self,
        *,
        scenario: TeamScenario,
        record: TeamSimulationRecord,
        threshold: float = 0.6,
        tier: int = 2,
        sim_runner: SimRunner | None = None,
    ) -> None:
        self._scenario = scenario
        self._record = record
        self._threshold = threshold
        self._tier = tier
        self._sim_runner = sim_runner

    @property
    def name(self) -> str:
        return f"holodeck_team:{self._record.simulation_id}"

    @property
    def tier(self) -> int:
        return self._tier

    @property
    def description(self) -> str:
        return self._scenario.summary

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def scenario(self) -> TeamScenario:
        return self._scenario

    @property
    def record(self) -> TeamSimulationRecord:
        return self._record

    async def run(self, agent_id: str, runtime: Any) -> "TestResult":
        from probos.cognitive.qualification import TestResult

        t0 = time.time()
        if self._sim_runner is None:
            return TestResult(
                agent_id=agent_id,
                test_name=self.name,
                tier=self._tier,
                score=0.5,
                passed=False,
                timestamp=time.time(),
                duration_ms=(time.time() - t0) * 1000,
                details={
                    "scenario_id": self._scenario.scenario_id,
                    "simulation_id": self._record.simulation_id,
                    "noop": True,
                    "note": (
                        "AD-510 v1 default sim_runner — supply runner via "
                        "TeamSimulationOrchestrator.set_sim_runner"
                    ),
                },
            )
        try:
            result = await self._sim_runner(
                self._scenario, self._record, runtime,
            )
        except Exception as exc:
            logger.warning(
                "AD-510: sim_runner raised for %s/%s: %s",
                self.name, agent_id, exc, exc_info=True,
            )
            return TestResult(
                agent_id=agent_id,
                test_name=self.name,
                tier=self._tier,
                score=0.0,
                passed=False,
                timestamp=time.time(),
                duration_ms=(time.time() - t0) * 1000,
                error=str(exc),
                details={
                    "scenario_id": self._scenario.scenario_id,
                    "simulation_id": self._record.simulation_id,
                },
            )
        if isinstance(result, TestResult):
            return result
        try:
            score, passed, details = result
        except Exception:
            logger.warning(
                "AD-510: sim_runner returned malformed result for %s; "
                "treating as failure", self.name,
            )
            return TestResult(
                agent_id=agent_id, test_name=self.name, tier=self._tier,
                score=0.0, passed=False, timestamp=time.time(),
                duration_ms=(time.time() - t0) * 1000,
                error="malformed sim_runner result",
            )
        merged_details = {
            "scenario_id": self._scenario.scenario_id,
            "simulation_id": self._record.simulation_id,
        }
        if isinstance(details, dict):
            merged_details.update(details)
        return TestResult(
            agent_id=agent_id,
            test_name=self.name,
            tier=self._tier,
            score=float(score),
            passed=bool(passed),
            timestamp=time.time(),
            duration_ms=(time.time() - t0) * 1000,
            details=merged_details,
        )


# ----------------------------------------------------------------------
# TeamSimulationStore — SQLite via ConnectionFactory + in-memory fallback.
# Mirrors AD-539b HolodeckScenarioStore shape at
# src/probos/holodeck/scenarios.py:381.
# ----------------------------------------------------------------------

_TEAM_STORE_SCHEMA = """\
CREATE TABLE IF NOT EXISTS team_simulation_records (
    simulation_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at REAL NOT NULL,
    completed_at REAL,
    last_score REAL,
    debrief_id TEXT,
    participants_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_team_sim_scenario ON team_simulation_records(scenario_id);

CREATE TABLE IF NOT EXISTS team_simulation_debriefs (
    debrief_id TEXT PRIMARY KEY,
    simulation_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    completed_at REAL NOT NULL,
    outcome_score REAL NOT NULL,
    passed INTEGER NOT NULL,
    time_elapsed REAL NOT NULL,
    time_limit_seconds REAL,
    notes TEXT NOT NULL DEFAULT '',
    participants_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_team_debrief_sim ON team_simulation_debriefs(simulation_id);
"""


def _participants_to_json(participants: tuple[TeamSimulationParticipant, ...]) -> str:
    import json
    return json.dumps([
        {
            "agent_id": p.agent_id,
            "department": p.department,
            "assigned_role": p.assigned_role,
            "entered_at": p.entered_at,
            "communication_only_constraint": p.communication_only_constraint,
        }
        for p in participants
    ])


def _participants_from_json(blob: str) -> tuple[TeamSimulationParticipant, ...]:
    import json
    data = json.loads(blob)
    return tuple(
        TeamSimulationParticipant(
            agent_id=d["agent_id"],
            department=d["department"],
            assigned_role=d["assigned_role"],
            entered_at=d["entered_at"],
            communication_only_constraint=d.get(
                "communication_only_constraint", False
            ),
        )
        for d in data
    )


class TeamSimulationStore:
    """Persists ``TeamSimulationRecord`` and ``DebriefRecord``.

    SQLite via ``probos.storage.sqlite_factory.default_factory`` when a
    ``data_dir`` is supplied; in-memory dict fallback otherwise.
    """

    def __init__(
        self,
        data_dir: str | Path | None = None,
        connection_factory: Any = None,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else None
        self._connection_factory = connection_factory
        self._db: Any = None
        self._records: dict[str, TeamSimulationRecord] = {}
        self._debriefs: dict[str, DebriefRecord] = {}

    async def start(self) -> None:
        if self._data_dir is None:
            return
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
        db_path = str(self._data_dir / "team_simulations.db")
        self._db = await self._connection_factory.connect(db_path)
        await self._db.executescript(_TEAM_STORE_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        if self._db is not None:
            try:
                await self._db.close()
            except Exception:
                pass
            self._db = None

    async def save_record(self, record: TeamSimulationRecord) -> None:
        self._records[record.simulation_id] = record
        if self._db is None:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO team_simulation_records "
            "(simulation_id, scenario_id, status, started_at, completed_at, "
            " last_score, debrief_id, participants_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.simulation_id, record.scenario_id, record.status,
                record.started_at, record.completed_at, record.last_score,
                record.debrief_id, _participants_to_json(record.participants),
            ),
        )
        await self._db.commit()

    async def get_record(self, simulation_id: str) -> TeamSimulationRecord | None:
        if simulation_id in self._records:
            return self._records[simulation_id]
        if self._db is None:
            return None
        cur = await self._db.execute(
            "SELECT simulation_id, scenario_id, status, started_at, "
            "completed_at, last_score, debrief_id, participants_json "
            "FROM team_simulation_records WHERE simulation_id = ?",
            (simulation_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        rec = TeamSimulationRecord(
            simulation_id=row[0], scenario_id=row[1], status=row[2],
            started_at=row[3], completed_at=row[4], last_score=row[5],
            debrief_id=row[6],
            participants=_participants_from_json(row[7]),
        )
        self._records[simulation_id] = rec
        return rec

    async def save_debrief(self, debrief: DebriefRecord) -> None:
        self._debriefs[debrief.debrief_id] = debrief
        if self._db is None:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO team_simulation_debriefs "
            "(debrief_id, simulation_id, scenario_id, started_at, completed_at, "
            " outcome_score, passed, time_elapsed, time_limit_seconds, notes, "
            " participants_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                debrief.debrief_id, debrief.simulation_id, debrief.scenario_id,
                debrief.started_at, debrief.completed_at, debrief.outcome_score,
                1 if debrief.passed else 0, debrief.time_elapsed,
                debrief.time_limit_seconds, debrief.notes,
                _participants_to_json(debrief.participants),
            ),
        )
        await self._db.commit()

    async def get_debrief(self, debrief_id: str) -> DebriefRecord | None:
        if debrief_id in self._debriefs:
            return self._debriefs[debrief_id]
        if self._db is None:
            return None
        cur = await self._db.execute(
            "SELECT debrief_id, simulation_id, scenario_id, started_at, "
            "completed_at, outcome_score, passed, time_elapsed, "
            "time_limit_seconds, notes, participants_json "
            "FROM team_simulation_debriefs WHERE debrief_id = ?",
            (debrief_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        deb = DebriefRecord(
            debrief_id=row[0], simulation_id=row[1], scenario_id=row[2],
            started_at=row[3], completed_at=row[4], outcome_score=row[5],
            passed=bool(row[6]), time_elapsed=row[7],
            time_limit_seconds=row[8], notes=row[9] or "",
            participants=_participants_from_json(row[10]),
        )
        self._debriefs[debrief_id] = deb
        return deb

    async def list_records_by_scenario(
        self, scenario_id: str,
    ) -> tuple[TeamSimulationRecord, ...]:
        out: list[TeamSimulationRecord] = [
            r for r in self._records.values() if r.scenario_id == scenario_id
        ]
        if self._db is None:
            return tuple(out)
        cur = await self._db.execute(
            "SELECT simulation_id, scenario_id, status, started_at, "
            "completed_at, last_score, debrief_id, participants_json "
            "FROM team_simulation_records WHERE scenario_id = ?",
            (scenario_id,),
        )
        rows = await cur.fetchall()
        seen = {r.simulation_id for r in out}
        for row in rows:
            if row[0] in seen:
                continue
            rec = TeamSimulationRecord(
                simulation_id=row[0], scenario_id=row[1], status=row[2],
                started_at=row[3], completed_at=row[4], last_score=row[5],
                debrief_id=row[6],
                participants=_participants_from_json(row[7]),
            )
            self._records[rec.simulation_id] = rec
            out.append(rec)
        return tuple(out)


# ----------------------------------------------------------------------
# TeamSimulationOrchestrator — orchestrates start/complete + events.
# Mirrors AD-539b HolodeckGapBridge shape at
# src/probos/holodeck/scenarios.py:473.
# ----------------------------------------------------------------------

DebriefPublisher = Callable[[DebriefRecord], Awaitable[Any]]


class TeamSimulationOrchestrator:
    """Orchestrates AD-510 team-simulation lifecycle.

    Public API:
        async start_simulation(scenario_id, team, *, role_rotation=None)
            -> TeamSimulationRecord | None
        async complete_simulation(simulation_id, score, *, passed=True,
                                  notes="") -> DebriefRecord | None
        async get_record(simulation_id) -> TeamSimulationRecord | None
        async list_records_by_scenario(scenario_id) -> tuple[...]

    Late-bind setters (Wave 5 conv #5):
        set_qualification_harness(harness)
        set_team_scenario_registry(registry)
        set_sim_runner(runner)
        set_debrief_publisher(publisher)
    """

    def __init__(
        self,
        config: Any,
        store: TeamSimulationStore,
        *,
        emit_event_fn: Callable[..., None] | None = None,
        qualification_harness: "QualificationHarness | None" = None,
        team_scenario_registry: TeamScenarioRegistry | None = None,
        sim_runner: SimRunner | None = None,
        debrief_publisher: DebriefPublisher | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._emit_event_fn = emit_event_fn
        self._qualification_harness = qualification_harness
        self._team_scenario_registry = team_scenario_registry
        self._sim_runner = sim_runner
        self._debrief_publisher = debrief_publisher

    # ── Late-bind setters (Wave 5 conv #5) ──────────────────────────
    def set_qualification_harness(self, harness: "QualificationHarness") -> None:
        self._qualification_harness = harness

    def set_team_scenario_registry(self, registry: TeamScenarioRegistry) -> None:
        self._team_scenario_registry = registry

    def set_sim_runner(self, runner: SimRunner) -> None:
        self._sim_runner = runner

    def set_debrief_publisher(self, publisher: DebriefPublisher) -> None:
        self._debrief_publisher = publisher

    @property
    def qualification_harness(self) -> "QualificationHarness | None":
        return self._qualification_harness

    @property
    def team_scenario_registry(self) -> TeamScenarioRegistry | None:
        return self._team_scenario_registry

    @property
    def store(self) -> TeamSimulationStore:
        return self._store

    # ── Public API ──────────────────────────────────────────────────

    async def start_simulation(
        self,
        scenario_id: str,
        team: list[tuple[str, str]],
        *,
        role_rotation: dict[str, str] | None = None,
    ) -> TeamSimulationRecord | None:
        """Start a team simulation.

        Returns the record, or None if the scenario is not found, the
        registry is unset, the bridge is disabled, or a required department
        is missing from the team.
        """
        if not getattr(self._config, "enabled", False):
            return None
        if self._team_scenario_registry is None:
            logger.warning(
                "AD-510: start_simulation called with no team_scenario_registry"
            )
            return None
        scenario = self._team_scenario_registry.get_scenario(scenario_id)
        if scenario is None:
            logger.warning(
                "AD-510: scenario %s not found in registry", scenario_id,
            )
            return None
        if not team:
            logger.warning("AD-510: empty team for scenario %s", scenario_id)
            return None

        # Required-department validation
        if getattr(self._config, "enforce_required_departments", True):
            team_depts = {d.lower() for _, d in team}
            missing = [
                d for d in scenario.required_departments
                if d.lower() not in team_depts
            ]
            if missing:
                logger.warning(
                    "AD-510: scenario %s missing required departments: %s",
                    scenario_id, missing,
                )
                return None

        rotation = role_rotation or {}
        now = time.time()
        participants: list[TeamSimulationParticipant] = []
        for agent_id, dept in team:
            assigned = rotation.get(agent_id, dept)
            participant = TeamSimulationParticipant(
                agent_id=agent_id,
                department=dept,
                assigned_role=assigned,
                entered_at=now,
                communication_only_constraint=scenario.communication_only,
            )
            participants.append(participant)

            # Role-rotation event — one per rotated participant
            if agent_id in rotation and rotation[agent_id] != dept:
                if scenario.role_rotation_allowed:
                    self._emit(EventType.TEAM_SIMULATION_ROLE_ROTATED, {
                        "scenario_id": scenario_id,
                        "agent_id": agent_id,
                        "original_role": dept,
                        "rotated_role": rotation[agent_id],
                    })
                else:
                    logger.warning(
                        "AD-510: role_rotation requested but scenario "
                        "%s does not allow rotation; skipping event for %s",
                        scenario_id, agent_id,
                    )

        # Communication-only constraint event
        if scenario.communication_only:
            self._emit(EventType.TEAM_SIMULATION_COMMUNICATION_CONSTRAINT_APPLIED, {
                "scenario_id": scenario_id,
                "participant_count": len(participants),
            })

        sim_id = f"team_sim_{uuid.uuid4().hex[:12]}"
        record = TeamSimulationRecord(
            simulation_id=sim_id,
            scenario_id=scenario_id,
            participants=tuple(participants),
            started_at=now,
            status="started",
        )

        # Build drill + register with harness (tier-2 log-and-degrade)
        drill = TeamSimulationDrill(
            scenario=scenario,
            record=record,
            threshold=getattr(self._config, "default_threshold", 0.6),
            tier=getattr(self._config, "default_tier", 2),
            sim_runner=self._sim_runner,
        )
        if (
            self._qualification_harness is not None
            and getattr(self._config, "auto_register_with_harness", True)
        ):
            try:
                self._qualification_harness.register_test(drill)
            except Exception:
                logger.warning(
                    "AD-510: harness.register_test raised for %s; "
                    "drill not registered", drill.name, exc_info=True,
                )

        # Persist record (tier-2 log-and-degrade)
        try:
            await self._store.save_record(record)
        except Exception:
            logger.warning(
                "AD-510: store.save_record raised for %s",
                sim_id, exc_info=True,
            )

        self._emit(EventType.TEAM_SIMULATION_STARTED, {
            "scenario_id": scenario_id,
            "simulation_id": sim_id,
            "participant_count": len(participants),
            "required_departments": list(scenario.required_departments),
            "time_limit_seconds": scenario.time_limit_seconds,
            "communication_only": scenario.communication_only,
        })
        return record

    async def complete_simulation(
        self,
        simulation_id: str,
        score: float,
        *,
        passed: bool = True,
        notes: str = "",
    ) -> DebriefRecord | None:
        """Complete a started simulation: persist debrief, update record,
        invoke optional debrief publisher.

        Returns the DebriefRecord, or None if the simulation_id is
        unknown.
        """
        record = await self._store.get_record(simulation_id)
        if record is None:
            logger.warning(
                "AD-510: complete_simulation called for unknown sim %s",
                simulation_id,
            )
            return None

        # Resolve scenario for time_limit_seconds metadata (tier-2)
        scenario_time_limit: float | None = None
        if self._team_scenario_registry is not None:
            sc = self._team_scenario_registry.get_scenario(record.scenario_id)
            if sc is not None:
                scenario_time_limit = sc.time_limit_seconds

        now = time.time()
        debrief_id = f"debrief_{uuid.uuid4().hex[:12]}"
        debrief = DebriefRecord(
            debrief_id=debrief_id,
            simulation_id=simulation_id,
            scenario_id=record.scenario_id,
            started_at=record.started_at,
            completed_at=now,
            outcome_score=float(score),
            passed=bool(passed),
            time_elapsed=max(0.0, now - record.started_at),
            time_limit_seconds=scenario_time_limit,
            participants=record.participants,
            notes=notes or "",
        )

        try:
            await self._store.save_debrief(debrief)
        except Exception:
            logger.warning(
                "AD-510: store.save_debrief raised for %s",
                debrief_id, exc_info=True,
            )

        self._emit(EventType.TEAM_SIMULATION_DEBRIEF_RECORDED, {
            "scenario_id": record.scenario_id,
            "simulation_id": simulation_id,
            "debrief_id": debrief_id,
            "outcome_score": float(score),
            "passed": bool(passed),
            "time_elapsed": debrief.time_elapsed,
        })

        if self._debrief_publisher is not None:
            try:
                await self._debrief_publisher(debrief)
            except Exception:
                logger.warning(
                    "AD-510: debrief_publisher raised for %s; debrief is "
                    "persisted but external publication failed",
                    debrief_id, exc_info=True,
                )

        updated = replace(
            record,
            status="completed",
            completed_at=now,
            last_score=float(score),
            debrief_id=debrief_id,
        )
        try:
            await self._store.save_record(updated)
        except Exception:
            logger.warning(
                "AD-510: store.save_record (update) raised for %s",
                simulation_id, exc_info=True,
            )

        self._emit(EventType.TEAM_SIMULATION_COMPLETED, {
            "scenario_id": record.scenario_id,
            "simulation_id": simulation_id,
            "debrief_id": debrief_id,
            "outcome_score": float(score),
            "passed": bool(passed),
        })
        return debrief

    async def get_record(self, simulation_id: str) -> TeamSimulationRecord | None:
        return await self._store.get_record(simulation_id)

    async def list_records_by_scenario(
        self, scenario_id: str,
    ) -> tuple[TeamSimulationRecord, ...]:
        return await self._store.list_records_by_scenario(scenario_id)

    # ── Internals ───────────────────────────────────────────────────

    def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        if self._emit_event_fn is None:
            return
        try:
            self._emit_event_fn(event_type, payload)
        except Exception:
            logger.warning(
                "AD-510: emit_event failed for %s", event_type, exc_info=True,
            )


__all__ = [
    "DebriefPublisher",
    "DebriefRecord",
    "SimRunner",
    "TeamScenario",
    "TeamScenarioRegistry",
    "TeamSimulationDrill",
    "TeamSimulationOrchestrator",
    "TeamSimulationParticipant",
    "TeamSimulationRecord",
    "TeamSimulationStore",
]
===END FILE===
```

## Section 2 — Append six EventTypes to `src/probos/events.py`

```
===MODIFY: src/probos/events.py===
===SEARCH===
    # AD-539b: Holodeck scenario generation from skill gaps
    HOLODECK_SCENARIO_GENERATED = "holodeck_scenario_generated"
    HOLODECK_SCENARIO_REGISTERED = "holodeck_scenario_registered"
    HOLODECK_SCENARIO_GAP_LINKED = "holodeck_scenario_gap_linked"
    HOLODECK_SCENARIO_OUTCOME_RECORDED = "holodeck_scenario_outcome_recorded"

    # ── Discovery-Based Capability Building (AD-512) ───────────────
===REPLACE===
    # AD-539b: Holodeck scenario generation from skill gaps
    HOLODECK_SCENARIO_GENERATED = "holodeck_scenario_generated"
    HOLODECK_SCENARIO_REGISTERED = "holodeck_scenario_registered"
    HOLODECK_SCENARIO_GAP_LINKED = "holodeck_scenario_gap_linked"
    HOLODECK_SCENARIO_OUTCOME_RECORDED = "holodeck_scenario_outcome_recorded"

    # AD-510: Holodeck team simulations — group discovery & collaboration
    TEAM_SCENARIO_REGISTERED = "team_scenario_registered"
    TEAM_SIMULATION_STARTED = "team_simulation_started"
    TEAM_SIMULATION_ROLE_ROTATED = "team_simulation_role_rotated"
    TEAM_SIMULATION_COMMUNICATION_CONSTRAINT_APPLIED = "team_simulation_communication_constraint_applied"
    TEAM_SIMULATION_DEBRIEF_RECORDED = "team_simulation_debrief_recorded"
    TEAM_SIMULATION_COMPLETED = "team_simulation_completed"

    # ── Discovery-Based Capability Building (AD-512) ───────────────
===END REPLACE===
```

## Section 3 — Add Pydantic config to `src/probos/config.py`

Two SEARCH/REPLACE pairs in the same `===MODIFY===` block.

```
===MODIFY: src/probos/config.py===
===SEARCH===
    enabled: bool = False
    auto_register_with_harness: bool = True
    default_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    default_tier: int = Field(default=2, ge=1, le=3)
    category_fallback: str = "construction"
    persist_to_sqlite: bool = False
    data_subdir: str = "holodeck_scenarios"
===REPLACE===
    enabled: bool = False
    auto_register_with_harness: bool = True
    default_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    default_tier: int = Field(default=2, ge=1, le=3)
    category_fallback: str = "construction"
    persist_to_sqlite: bool = False
    data_subdir: str = "holodeck_scenarios"


class HolodeckTeamSimulationConfig(BaseModel):
    """AD-510: Holodeck team simulations — group discovery & collaboration.

    Default-False per AD-695 transitional-flag precedent: enabling the
    orchestrator causes ``TeamSimulationOrchestrator.start_simulation``
    to register a runnable ``TeamSimulationDrill`` with the AD-477
    ``QualificationHarness`` for every started simulation. v1 ships
    dormant — operators flip ``enabled=True`` once an AD-486 cohort
    reaches Phase α with crew-tier agents available across >=2
    departments to populate team rosters.
    """

    enabled: bool = False
    auto_register_with_harness: bool = True
    default_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    default_tier: int = Field(default=2, ge=1, le=3)
    enforce_required_departments: bool = True
    persist_to_sqlite: bool = False
    data_subdir: str = "team_simulations"
===END REPLACE===
===SEARCH===
    holodeck_birth_chamber: HolodeckBirthChamberConfig = HolodeckBirthChamberConfig()
    holodeck_scenarios: HolodeckScenarioConfig = HolodeckScenarioConfig()
    naming: NamingConfig = NamingConfig()  # AD-499
===REPLACE===
    holodeck_birth_chamber: HolodeckBirthChamberConfig = HolodeckBirthChamberConfig()
    holodeck_scenarios: HolodeckScenarioConfig = HolodeckScenarioConfig()
    team_simulations: HolodeckTeamSimulationConfig = HolodeckTeamSimulationConfig()
    naming: NamingConfig = NamingConfig()  # AD-499
===END REPLACE===
```

## Section 4 — Add finalize wirer + invocation in `src/probos/startup/finalize.py`

Two SEARCH/REPLACE pairs.

```
===MODIFY: src/probos/startup/finalize.py===
===SEARCH===
def _wire_holodeck_scenarios(*, runtime: Any, config: "SystemConfig") -> bool:
===REPLACE===
def _wire_holodeck_team_simulations(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-510 v1: Wire TeamSimulationOrchestrator + TeamScenarioRegistry.

    Default-False per AD-695 transitional-flag precedent. When disabled,
    no orchestrator is constructed; ``runtime.team_simulation_orchestrator``
    and ``runtime.team_scenario_registry`` are NOT set.
    """
    cfg = getattr(config, "team_simulations", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.holodeck.team_simulations import (
        TeamScenarioRegistry,
        TeamSimulationOrchestrator,
        TeamSimulationStore,
    )

    emit_fn = getattr(runtime, "emit_event", None)

    data_dir: Any = None
    if cfg.persist_to_sqlite:
        ship_data_dir = getattr(runtime, "data_dir", None)
        if ship_data_dir is not None:
            from pathlib import Path as _Path
            data_dir = _Path(ship_data_dir) / cfg.data_subdir
            data_dir.mkdir(parents=True, exist_ok=True)

    registry = TeamScenarioRegistry()
    registry.emit_event = emit_fn
    runtime.team_scenario_registry = registry  # public (Wave 5 conv #1)

    store = TeamSimulationStore(data_dir=data_dir)

    orchestrator = TeamSimulationOrchestrator(
        config=cfg,
        store=store,
        emit_event_fn=emit_fn,
        qualification_harness=getattr(runtime, "qualification_harness", None),
        team_scenario_registry=registry,
    )
    runtime.team_simulation_orchestrator = orchestrator  # public (Wave 5 conv #1)

    logger.info(
        "AD-510: Holodeck team simulations v1 initialized "
        "(harness=%s, registry=%s, persist=%s)",
        orchestrator.qualification_harness is not None,
        orchestrator.team_scenario_registry is not None,
        cfg.persist_to_sqlite,
    )
    return True


def _wire_holodeck_scenarios(*, runtime: Any, config: "SystemConfig") -> bool:
===END REPLACE===
===SEARCH===
    if _wire_holodeck_scenarios(runtime=runtime, config=config):
        logger.info("AD-539b: Holodeck Scenario Generation v1 wired during finalization")

    if _wire_discovery_learning(runtime=runtime, config=config):
        logger.info("AD-512: Discovery Learning v1 wired during finalization")
===REPLACE===
    if _wire_holodeck_scenarios(runtime=runtime, config=config):
        logger.info("AD-539b: Holodeck Scenario Generation v1 wired during finalization")

    if _wire_holodeck_team_simulations(runtime=runtime, config=config):
        logger.info("AD-510: Holodeck Team Simulations v1 wired during finalization")

    if _wire_discovery_learning(runtime=runtime, config=config):
        logger.info("AD-512: Discovery Learning v1 wired during finalization")
===END REPLACE===
```

## Section 5 — Re-export from `src/probos/holodeck/__init__.py`

```
===MODIFY: src/probos/holodeck/__init__.py===
===SEARCH===
from probos.holodeck.scenarios import (
    GapScenarioGenerator,
    HolodeckGapBridge,
    HolodeckGapDrill,
    HolodeckScenarioStore,
    ScenarioGapLink,
    ScenarioOutcome,
)
from probos.holodeck.scheduler import DepartmentActivationScheduler

__all__ = [
    "AffectiveBaselineCheck",
    "AffectiveObservation",
    "BirthChamber",
    "BirthChamberRecord",
    "DepartmentActivationScheduler",
    "GapScenarioGenerator",
    "HolodeckGapBridge",
    "HolodeckGapDrill",
    "HolodeckPhase",
    "HolodeckScenarioStore",
    "NoOpAffectiveBaselineCheck",
    "ScenarioGapLink",
    "ScenarioOutcome",
]
===REPLACE===
from probos.holodeck.scenarios import (
    GapScenarioGenerator,
    HolodeckGapBridge,
    HolodeckGapDrill,
    HolodeckScenarioStore,
    ScenarioGapLink,
    ScenarioOutcome,
)
from probos.holodeck.scheduler import DepartmentActivationScheduler
from probos.holodeck.team_simulations import (
    DebriefRecord,
    TeamScenario,
    TeamScenarioRegistry,
    TeamSimulationDrill,
    TeamSimulationOrchestrator,
    TeamSimulationParticipant,
    TeamSimulationRecord,
    TeamSimulationStore,
)

__all__ = [
    "AffectiveBaselineCheck",
    "AffectiveObservation",
    "BirthChamber",
    "BirthChamberRecord",
    "DebriefRecord",
    "DepartmentActivationScheduler",
    "GapScenarioGenerator",
    "HolodeckGapBridge",
    "HolodeckGapDrill",
    "HolodeckPhase",
    "HolodeckScenarioStore",
    "NoOpAffectiveBaselineCheck",
    "ScenarioGapLink",
    "ScenarioOutcome",
    "TeamScenario",
    "TeamScenarioRegistry",
    "TeamSimulationDrill",
    "TeamSimulationOrchestrator",
    "TeamSimulationParticipant",
    "TeamSimulationRecord",
    "TeamSimulationStore",
]
===END REPLACE===
```

## Section 6 — New test file `tests/test_ad510_team_simulations.py`

```
===FILE: tests/test_ad510_team_simulations.py===
"""AD-510 v1 — Holodeck Team Simulations test suite (~46 tests / 8 classes).

Floor: 38 — exceeded by 8.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.config import HolodeckTeamSimulationConfig, SystemConfig
from probos.events import EventType
from probos.holodeck.team_simulations import (
    DebriefRecord,
    TeamScenario,
    TeamScenarioRegistry,
    TeamSimulationDrill,
    TeamSimulationOrchestrator,
    TeamSimulationParticipant,
    TeamSimulationRecord,
    TeamSimulationStore,
    _DEFAULT_TEAM_SCENARIOS,
)


# ──────────────────────────────────────────────────────────────────────
# Class 1: EventTypes (6)
# ──────────────────────────────────────────────────────────────────────

class TestAd510EventTypes:
    def test_team_scenario_registered_value(self):
        assert EventType.TEAM_SCENARIO_REGISTERED.value == "team_scenario_registered"

    def test_team_simulation_started_value(self):
        assert EventType.TEAM_SIMULATION_STARTED.value == "team_simulation_started"

    def test_team_simulation_role_rotated_value(self):
        assert EventType.TEAM_SIMULATION_ROLE_ROTATED.value == "team_simulation_role_rotated"

    def test_team_simulation_communication_constraint_applied_value(self):
        assert (
            EventType.TEAM_SIMULATION_COMMUNICATION_CONSTRAINT_APPLIED.value
            == "team_simulation_communication_constraint_applied"
        )

    def test_team_simulation_debrief_recorded_value(self):
        assert EventType.TEAM_SIMULATION_DEBRIEF_RECORDED.value == "team_simulation_debrief_recorded"

    def test_team_simulation_completed_value(self):
        assert EventType.TEAM_SIMULATION_COMPLETED.value == "team_simulation_completed"


# ──────────────────────────────────────────────────────────────────────
# Class 2: HolodeckTeamSimulationConfig (6)
# ──────────────────────────────────────────────────────────────────────

class TestAd510Config:
    def test_default_disabled(self):
        cfg = HolodeckTeamSimulationConfig()
        assert cfg.enabled is False

    def test_default_auto_register_true(self):
        assert HolodeckTeamSimulationConfig().auto_register_with_harness is True

    def test_default_threshold_in_range(self):
        cfg = HolodeckTeamSimulationConfig()
        assert 0.0 <= cfg.default_threshold <= 1.0
        assert cfg.default_threshold == 0.6

    def test_default_tier_is_two(self):
        assert HolodeckTeamSimulationConfig().default_tier == 2

    def test_default_enforce_required_departments_true(self):
        assert HolodeckTeamSimulationConfig().enforce_required_departments is True

    def test_attached_to_system_config(self):
        sc = SystemConfig()
        assert hasattr(sc, "team_simulations")
        assert isinstance(sc.team_simulations, HolodeckTeamSimulationConfig)


# ──────────────────────────────────────────────────────────────────────
# Class 3: TeamScenario + TeamScenarioRegistry (6)
# ──────────────────────────────────────────────────────────────────────

class TestAd510ScenarioRegistry:
    def test_default_catalog_has_six_scenarios(self):
        assert len(_DEFAULT_TEAM_SCENARIOS) == 6

    def test_catalog_covers_all_axes(self):
        scenarios = list(_DEFAULT_TEAM_SCENARIOS)
        # Mixed-dept (all 6 require >=2 departments)
        assert all(len(s.required_departments) >= 2 for s in scenarios)
        # At least one time-pressured
        assert any(s.time_limit_seconds is not None for s in scenarios)
        # At least one communication-only
        assert any(s.communication_only for s in scenarios)
        # At least one role-rotation-allowed
        assert any(s.role_rotation_allowed for s in scenarios)

    def test_get_scenario_returns_scenario(self):
        reg = TeamScenarioRegistry()
        s = reg.get_scenario("medical_engineering_wellness_diagnose")
        assert s is not None
        assert "medical" in s.required_departments
        assert "engineering" in s.required_departments

    def test_get_scenario_missing_returns_none(self):
        assert TeamScenarioRegistry().get_scenario("nope") is None

    def test_list_by_department_filters_correctly(self):
        reg = TeamScenarioRegistry()
        eng = reg.list_by_department("engineering")
        assert all("engineering" in s.required_departments for s in eng)
        assert len(eng) >= 2

    def test_list_by_time_pressure_returns_only_timed(self):
        reg = TeamScenarioRegistry()
        timed = reg.list_by_time_pressure()
        assert all(s.time_limit_seconds is not None for s in timed)
        assert len(timed) >= 1

    def test_register_scenario_emits_event(self):
        reg = TeamScenarioRegistry()
        events: list = []
        reg.emit_event = lambda et, payload: events.append((et, payload))
        new_s = TeamScenario(
            scenario_id="custom_x",
            title="Custom",
            summary="Custom scenario",
            required_departments=("medical", "operations"),
            skills_tested=("communication",),
            learning_objectives=("Learn",),
        )
        reg.register_scenario(new_s)
        assert reg.get_scenario("custom_x") is new_s
        assert len(events) == 1
        assert events[0][0] is EventType.TEAM_SCENARIO_REGISTERED
        assert events[0][1]["scenario_id"] == "custom_x"


# ──────────────────────────────────────────────────────────────────────
# Class 4: Frozen dataclasses (4)
# ──────────────────────────────────────────────────────────────────────

class TestAd510Dataclasses:
    def test_team_simulation_participant_frozen(self):
        p = TeamSimulationParticipant(
            agent_id="a1", department="medical",
            assigned_role="medical", entered_at=1000.0,
        )
        with pytest.raises(Exception):
            p.assigned_role = "engineering"  # type: ignore[misc]

    def test_team_simulation_record_defaults(self):
        r = TeamSimulationRecord(
            simulation_id="s1", scenario_id="sc1",
            participants=tuple(), started_at=1000.0,
        )
        assert r.status == "started"
        assert r.completed_at is None
        assert r.last_score is None
        assert r.debrief_id is None

    def test_debrief_record_required_fields(self):
        d = DebriefRecord(
            debrief_id="d1", simulation_id="s1", scenario_id="sc1",
            started_at=1000.0, completed_at=1100.0,
            outcome_score=0.7, passed=True, time_elapsed=100.0,
            participants=tuple(),
        )
        assert d.notes == ""
        assert d.time_limit_seconds is None

    def test_team_scenario_default_difficulty(self):
        s = TeamScenario(
            scenario_id="x", title="x", summary="x",
            required_departments=("a", "b"),
            skills_tested=("y",),
            learning_objectives=("z",),
        )
        assert s.difficulty == 0.5
        assert s.communication_only is False
        assert s.role_rotation_allowed is False
        assert s.time_limit_seconds is None


# ──────────────────────────────────────────────────────────────────────
# Class 5: TeamSimulationDrill (5) — implements QualificationTest Protocol
# ──────────────────────────────────────────────────────────────────────

class TestAd510Drill:
    def _make_drill(self, sim_runner=None):
        scenario = TeamScenario(
            scenario_id="x", title="x", summary="x scenario summary",
            required_departments=("a", "b"),
            skills_tested=("y",),
            learning_objectives=("z",),
        )
        record = TeamSimulationRecord(
            simulation_id="sim_alpha", scenario_id="x",
            participants=tuple(), started_at=1000.0,
        )
        return TeamSimulationDrill(
            scenario=scenario, record=record, sim_runner=sim_runner,
        )

    def test_protocol_compliance(self):
        from probos.cognitive.qualification import QualificationTest
        d = self._make_drill()
        assert isinstance(d, QualificationTest)

    def test_name_format(self):
        assert self._make_drill().name == "holodeck_team:sim_alpha"

    def test_tier_threshold_description(self):
        d = self._make_drill()
        assert d.tier == 2
        assert d.threshold == 0.6
        assert d.description == "x scenario summary"

    @pytest.mark.asyncio
    async def test_run_with_no_runner_returns_noop_result(self):
        d = self._make_drill()
        rt = MagicMock(spec=[])
        result = await d.run("agent_007", rt)
        assert result.score == 0.5
        assert result.passed is False
        assert result.details["noop"] is True
        assert result.details["scenario_id"] == "x"
        assert result.details["simulation_id"] == "sim_alpha"

    @pytest.mark.asyncio
    async def test_run_with_runner_returns_runner_result(self):
        async def runner(scenario, record, runtime):
            return (0.85, True, {"reason": "well-done"})
        d = self._make_drill(sim_runner=runner)
        result = await d.run("agent_007", MagicMock(spec=[]))
        assert result.score == 0.85
        assert result.passed is True
        assert result.details["reason"] == "well-done"


# ──────────────────────────────────────────────────────────────────────
# Class 6: TeamSimulationStore (4)
# ──────────────────────────────────────────────────────────────────────

class TestAd510Store:
    @pytest.mark.asyncio
    async def test_in_memory_save_and_get_record(self):
        s = TeamSimulationStore(data_dir=None)
        await s.start()
        rec = TeamSimulationRecord(
            simulation_id="m1", scenario_id="sc1",
            participants=tuple(), started_at=1.0,
        )
        await s.save_record(rec)
        assert await s.get_record("m1") == rec
        await s.stop()

    @pytest.mark.asyncio
    async def test_save_and_get_debrief_in_memory(self):
        s = TeamSimulationStore(data_dir=None)
        await s.start()
        d = DebriefRecord(
            debrief_id="d1", simulation_id="s1", scenario_id="sc1",
            started_at=1.0, completed_at=2.0,
            outcome_score=0.8, passed=True, time_elapsed=1.0,
            participants=tuple(),
        )
        await s.save_debrief(d)
        assert await s.get_debrief("d1") == d
        await s.stop()

    @pytest.mark.asyncio
    async def test_list_records_by_scenario(self):
        s = TeamSimulationStore(data_dir=None)
        await s.start()
        for i in range(3):
            await s.save_record(TeamSimulationRecord(
                simulation_id=f"s{i}", scenario_id="sc",
                participants=tuple(), started_at=float(i),
            ))
        await s.save_record(TeamSimulationRecord(
            simulation_id="other", scenario_id="other_sc",
            participants=tuple(), started_at=99.0,
        ))
        out = await s.list_records_by_scenario("sc")
        assert len(out) == 3
        assert all(r.scenario_id == "sc" for r in out)
        await s.stop()

    @pytest.mark.asyncio
    async def test_sqlite_persistence_roundtrip(self, tmp_path):
        s = TeamSimulationStore(data_dir=tmp_path)
        await s.start()
        rec = TeamSimulationRecord(
            simulation_id="persisted", scenario_id="sc",
            participants=(TeamSimulationParticipant(
                agent_id="a1", department="medical",
                assigned_role="medical", entered_at=1.0,
            ),),
            started_at=1.0,
        )
        await s.save_record(rec)
        await s.stop()
        s2 = TeamSimulationStore(data_dir=tmp_path)
        await s2.start()
        loaded = await s2.get_record("persisted")
        assert loaded is not None
        assert loaded.simulation_id == "persisted"
        assert len(loaded.participants) == 1
        assert loaded.participants[0].agent_id == "a1"
        await s2.stop()


# ──────────────────────────────────────────────────────────────────────
# Class 7: TeamSimulationOrchestrator (12)
# ──────────────────────────────────────────────────────────────────────

class TestAd510Orchestrator:
    def _config(self, **kw) -> HolodeckTeamSimulationConfig:
        return HolodeckTeamSimulationConfig(enabled=True, **kw)

    async def _make(self, config=None):
        config = config or self._config()
        store = TeamSimulationStore(data_dir=None)
        await store.start()
        registry = TeamScenarioRegistry()
        events: list = []
        orch = TeamSimulationOrchestrator(
            config=config,
            store=store,
            emit_event_fn=lambda et, p: events.append((et, p)),
            team_scenario_registry=registry,
        )
        return orch, store, registry, events

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self):
        orch, _, _, _ = await self._make(
            HolodeckTeamSimulationConfig(enabled=False)
        )
        result = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",
            [("a1", "medical"), ("a2", "engineering")],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_scenario_returns_none(self):
        orch, _, _, _ = await self._make()
        result = await orch.start_simulation(
            "nope_does_not_exist",
            [("a1", "medical"), ("a2", "engineering")],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_required_dept_returns_none(self):
        orch, _, _, _ = await self._make()
        result = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",
            [("a1", "medical"), ("a2", "operations")],  # missing engineering
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_happy_path_emits_started_event(self):
        orch, store, _, events = await self._make()
        rec = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",
            [("a1", "medical"), ("a2", "engineering")],
        )
        assert rec is not None
        assert rec.status == "started"
        started_events = [e for e in events if e[0] is EventType.TEAM_SIMULATION_STARTED]
        assert len(started_events) == 1
        assert started_events[0][1]["scenario_id"] == "medical_engineering_wellness_diagnose"
        assert await store.get_record(rec.simulation_id) == rec

    @pytest.mark.asyncio
    async def test_role_rotation_emits_event(self):
        orch, _, _, events = await self._make()
        rec = await orch.start_simulation(
            "engineering_science_research_buildout",  # role_rotation_allowed=True
            [("a1", "engineering"), ("a2", "science")],
            role_rotation={"a1": "science"},
        )
        assert rec is not None
        rotated = [e for e in events if e[0] is EventType.TEAM_SIMULATION_ROLE_ROTATED]
        assert len(rotated) == 1
        assert rotated[0][1]["agent_id"] == "a1"
        assert rotated[0][1]["original_role"] == "engineering"
        assert rotated[0][1]["rotated_role"] == "science"
        # And participant carries the rotated role
        assert rec.participants[0].assigned_role == "science"

    @pytest.mark.asyncio
    async def test_role_rotation_not_emitted_when_scenario_disallows(self):
        orch, _, _, events = await self._make()
        rec = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",  # role_rotation_allowed=False
            [("a1", "medical"), ("a2", "engineering")],
            role_rotation={"a1": "engineering"},
        )
        assert rec is not None
        rotated = [e for e in events if e[0] is EventType.TEAM_SIMULATION_ROLE_ROTATED]
        assert rotated == []

    @pytest.mark.asyncio
    async def test_communication_only_emits_event(self):
        orch, _, _, events = await self._make()
        rec = await orch.start_simulation(
            "medical_communications_outbreak_brief",  # communication_only=True
            [("a1", "medical"), ("a2", "communications")],
        )
        assert rec is not None
        comm_events = [
            e for e in events
            if e[0] is EventType.TEAM_SIMULATION_COMMUNICATION_CONSTRAINT_APPLIED
        ]
        assert len(comm_events) == 1
        assert all(p.communication_only_constraint for p in rec.participants)

    @pytest.mark.asyncio
    async def test_time_limit_seconds_in_started_payload(self):
        orch, _, _, events = await self._make()
        await orch.start_simulation(
            "bridge_engineering_emergency_routing",  # 60s
            [("a1", "operations"), ("a2", "engineering")],
        )
        started = next(
            e for e in events if e[0] is EventType.TEAM_SIMULATION_STARTED
        )
        assert started[1]["time_limit_seconds"] == 60.0

    @pytest.mark.asyncio
    async def test_harness_register_test_called(self):
        orch, _, _, _ = await self._make()
        harness = MagicMock()
        harness.register_test = MagicMock()
        orch.set_qualification_harness(harness)
        rec = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",
            [("a1", "medical"), ("a2", "engineering")],
        )
        assert rec is not None
        harness.register_test.assert_called_once()
        registered = harness.register_test.call_args[0][0]
        assert registered.name == f"holodeck_team:{rec.simulation_id}"

    @pytest.mark.asyncio
    async def test_complete_simulation_persists_debrief_and_emits(self):
        orch, store, _, events = await self._make()
        rec = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",
            [("a1", "medical"), ("a2", "engineering")],
        )
        assert rec is not None
        debrief = await orch.complete_simulation(
            rec.simulation_id, score=0.82, passed=True, notes="Good handoff",
        )
        assert debrief is not None
        assert debrief.outcome_score == 0.82
        assert debrief.passed is True
        assert debrief.notes == "Good handoff"
        assert await store.get_debrief(debrief.debrief_id) == debrief
        # Updated record reflects completion
        updated = await store.get_record(rec.simulation_id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.last_score == 0.82
        assert updated.debrief_id == debrief.debrief_id
        # Both events emitted
        kinds = [e[0] for e in events]
        assert EventType.TEAM_SIMULATION_DEBRIEF_RECORDED in kinds
        assert EventType.TEAM_SIMULATION_COMPLETED in kinds

    @pytest.mark.asyncio
    async def test_complete_simulation_unknown_id_returns_none(self):
        orch, _, _, _ = await self._make()
        result = await orch.complete_simulation("does_not_exist", score=0.5)
        assert result is None

    @pytest.mark.asyncio
    async def test_debrief_publisher_invoked_and_exception_logged(self, caplog):
        orch, _, _, _ = await self._make()
        publisher = AsyncMock()
        orch.set_debrief_publisher(publisher)
        rec = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",
            [("a1", "medical"), ("a2", "engineering")],
        )
        assert rec is not None
        debrief = await orch.complete_simulation(rec.simulation_id, score=0.7)
        assert debrief is not None
        publisher.assert_awaited_once_with(debrief)
        # Exception path — replace publisher; orchestrator must log+continue
        bad = AsyncMock(side_effect=RuntimeError("publisher down"))
        orch.set_debrief_publisher(bad)
        rec2 = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",
            [("a1", "medical"), ("a2", "engineering")],
        )
        assert rec2 is not None
        with caplog.at_level("WARNING"):
            d2 = await orch.complete_simulation(rec2.simulation_id, score=0.5)
        assert d2 is not None
        assert any("debrief_publisher raised" in m for m in caplog.messages)


# ──────────────────────────────────────────────────────────────────────
# Class 8: Startup wiring (3)
# ──────────────────────────────────────────────────────────────────────

class TestAd510StartupWiring:
    def test_disabled_does_not_set_attributes(self):
        from types import SimpleNamespace
        from probos.startup.finalize import _wire_holodeck_team_simulations
        sc = SystemConfig()
        rt = SimpleNamespace()
        wired = _wire_holodeck_team_simulations(runtime=rt, config=sc)
        assert wired is False
        assert not hasattr(rt, "team_simulation_orchestrator")
        assert not hasattr(rt, "team_scenario_registry")

    def test_enabled_sets_orchestrator_and_registry(self):
        from types import SimpleNamespace
        from probos.startup.finalize import _wire_holodeck_team_simulations
        sc = SystemConfig()
        sc.team_simulations.enabled = True
        rt = SimpleNamespace(emit_event=lambda et, p: None)
        wired = _wire_holodeck_team_simulations(runtime=rt, config=sc)
        assert wired is True
        assert isinstance(rt.team_simulation_orchestrator, TeamSimulationOrchestrator)
        assert isinstance(rt.team_scenario_registry, TeamScenarioRegistry)

    def test_late_bind_harness_attached_when_present(self):
        from types import SimpleNamespace
        from probos.startup.finalize import _wire_holodeck_team_simulations
        sc = SystemConfig()
        sc.team_simulations.enabled = True
        harness = MagicMock()
        rt = SimpleNamespace(
            emit_event=lambda et, p: None,
            qualification_harness=harness,
        )
        _wire_holodeck_team_simulations(runtime=rt, config=sc)
        assert rt.team_simulation_orchestrator.qualification_harness is harness
===END FILE===
```

## What this AD does NOT change

- No modification of `BaseAgent` / `IntentMessage` / consensus / trust / Hebbian routing.
- No modification of `HolodeckGapBridge` / `HolodeckScenarioStore` / `HolodeckGapDrill` / `GapScenarioGenerator` (AD-539b surface is read-only as a precedent).
- No modification of `BirthChamber` / `DepartmentActivationScheduler` (AD-486 surface is read-only).
- No modification of `QualificationHarness` / `QualificationTest` Protocol / `QualificationStore` (AD-477 surface is consumed read-only via `register_test`).
- No modification of `DiscoveryScenarioRegistry` / `_DEFAULT_SCENARIOS` (AD-512 surface is referenced by precedent only — not imported).
- No modification of `WardRoomService` (debrief publisher is supplied externally; this AD does NOT wire ward-room).
- No new EventType outside the six declared in Section 0.
- No new Pydantic config outside the one declared in Section 3.
- No new public attribute on `runtime` outside `team_scenario_registry` and `team_simulation_orchestrator` (set inside the new wirer only).
- No HXI surface, slash command, or REST API endpoint.
- No LLM-driven debrief synthesis (AD-510-d, FF-deferred).
- No trait-adaptive team composition (AD-510-e, FF-deferred).
- No GH issue minted for AD-510-d / AD-510-e — both are letter-suffixed forcing-function descriptors, NOT new tracking issues.

## Tracking

| Tracker | Update |
|---------|--------|
| `prompts/wave-plan.yaml` | W101 entry appended (status: pending), see Section 7 below. |
| `PROGRESS.md` | Builder appends W101 close paragraph mirroring W100 format. |
| `docs/development/roadmap.md` | Builder flips AD-510 entry from `(planned, OSS, depends: AD-486, AD-507)` to `(v1 partial — registry/orchestrator/drill/store/debrief/events/config/wirer shipped Wave 101; AD-510-d LLM debrief synthesis + AD-510-e trait-adaptive composition deferred with forcing functions)`. |
| `decisions-era-4-evolution.md` | Builder flips AD-510 row at `:1347` to reference Wave 101 close. |
| `DECISIONS.md` | NO change. AD-510 is pre-allocated. |

## Section 7 — Wave-plan entry append

```
===MODIFY: prompts/wave-plan.yaml===
===SEARCH===
  - id: "100"
    title: "AD-539b v1 Holodeck Scenario Generation from Skill Gaps (closes #12)"
    kind: single
    depends_on: ["99"]
    dispatch_prompt: "prompts/WAVE-100-DISPATCH.md"
    prompts_already_drafted: true
    prompt_paths:
      - "prompts/ad-539b-holodeck-scenario-generation-v1.md"
    builder_required: true
    issues_to_close: [12]
    status: pending
===REPLACE===
  - id: "100"
    title: "AD-539b v1 Holodeck Scenario Generation from Skill Gaps (closes #12)"
    kind: single
    depends_on: ["99"]
    dispatch_prompt: "prompts/WAVE-100-DISPATCH.md"
    prompts_already_drafted: true
    prompt_paths:
      - "prompts/ad-539b-holodeck-scenario-generation-v1.md"
    builder_required: true
    issues_to_close: [12]
    status: pending

  - id: "101"
    title: "AD-510 v1 Holodeck Team Simulations: Group Discovery & Collaboration (closes #92)"
    kind: single
    depends_on: ["100"]
    dispatch_prompt: "prompts/WAVE-101-DISPATCH.md"
    prompts_already_drafted: true
    prompt_paths:
      - "prompts/ad-510-holodeck-team-simulations-v1.md"
    builder_required: true
    issues_to_close: [92]
    status: pending
===END REPLACE===
```

## Acceptance criteria

1. New module `src/probos/holodeck/team_simulations.py` ships exactly the eight public classes declared in Section 1: `TeamScenario`, `TeamScenarioRegistry`, `TeamSimulationParticipant`, `DebriefRecord`, `TeamSimulationRecord`, `TeamSimulationDrill`, `TeamSimulationStore`, `TeamSimulationOrchestrator`. `_DEFAULT_TEAM_SCENARIOS` ships exactly 6 entries spanning all 5 per-scenario axes.
2. Six new EventType values appended at the precise insertion site declared in Section 2. AD-486/539b cluster grouping preserved.
3. `HolodeckTeamSimulationConfig` Pydantic model added at the precise insertion site declared in Section 3. `team_simulations: HolodeckTeamSimulationConfig = HolodeckTeamSimulationConfig()` field added to `SystemConfig` immediately after the `holodeck_scenarios` field.
4. `_wire_holodeck_team_simulations` wirer added at the precise insertion site declared in Section 4. Invocation site appended to the same wirer-cascade block that hosts `_wire_holodeck_scenarios`.
5. Holodeck package `__init__.py` re-exports the eight new public names per Section 5.
6. New test file `tests/test_ad510_team_simulations.py` ships ≥38 tests across 8 classes (target 46).
7. Full pytest gate at `pytest tests/ -q -n 4 --dist=loadfile` reaches ≥12352 passing (baseline 12314 + floor 38), target ≥12360.
8. Builder commit message: `AD-510: Holodeck team simulations v1 (registry+orchestrator+drill+store+debrief+events+config+wirer) (+NN tests)`.
9. Wave 101 archive commit moves `prompts/WAVE-101-DISPATCH.md` and `prompts/ad-510-holodeck-team-simulations-v1.md` into `prompts/archive/`.
10. GH issue #92 closure comment includes the test-delta, the fleet-level overlay descriptor-only note (per Wave 100 precedent — placeholder forms only, no banned literal patterns), and the two AD-510-d / AD-510-e forcing-function descriptors.
11. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (HEAD `15fed52`, 2026-05-07)

```
git rev-parse HEAD
  15fed52

Select-String -Path src\probos\events.py -Pattern "HOLODECK_SCENARIO_OUTCOME_RECORDED"
  src/probos/events.py:399: HOLODECK_SCENARIO_OUTCOME_RECORDED = "holodeck_scenario_outcome_recorded"
  (insertion site for Section 2 SEARCH/REPLACE confirmed.)

Select-String -Path src\probos\config.py -Pattern "data_subdir = ""holodeck_scenarios""|holodeck_scenarios: HolodeckScenarioConfig"
  src/probos/config.py:1810:    data_subdir: str = "holodeck_scenarios"
  src/probos/config.py:2818:    holodeck_scenarios: HolodeckScenarioConfig = HolodeckScenarioConfig()
  (insertion sites for Section 3 SEARCH/REPLACE confirmed.)

Select-String -Path src\probos\startup\finalize.py -Pattern "^def _wire_holodeck_scenarios|^def _wire_discovery_learning|_wire_holodeck_scenarios.runtime=runtime"
  src/probos/startup/finalize.py:242: def _wire_holodeck_scenarios(*, runtime: Any, config: "SystemConfig") -> bool:
  src/probos/startup/finalize.py:294: def _wire_discovery_learning(*, runtime: Any, config: "SystemConfig") -> bool:
  src/probos/startup/finalize.py:1598:    if _wire_holodeck_scenarios(runtime=runtime, config=config):
  (insertion sites for Section 4 SEARCH/REPLACE confirmed.)

Select-String -Path src\probos\holodeck\__init__.py -Pattern "^from probos.holodeck.scheduler|^__all__ = \["
  src/probos/holodeck/__init__.py:29: from probos.holodeck.scheduler import DepartmentActivationScheduler
  src/probos/holodeck/__init__.py:31: __all__ = [
  (insertion sites for Section 5 SEARCH/REPLACE confirmed.)

Select-String -Path src\probos\cognitive\qualification.py -Pattern "^class QualificationTest|register_test|class TestResult"
  src/probos/cognitive/qualification.py:39:  class QualificationTest(Protocol):
  src/probos/cognitive/qualification.py:74:  class TestResult:
  src/probos/cognitive/qualification.py:371: def register_test(self, test: QualificationTest) -> None:
  (Protocol shape and register_test signature confirmed.)

Select-String -Path src\probos\holodeck\scenarios.py -Pattern "from probos.storage.sqlite_factory import default_factory"
  src/probos/holodeck/scenarios.py:403: from probos.storage.sqlite_factory import default_factory
  (ConnectionFactory access pattern reused in TeamSimulationStore.start.)

git ls-files src/probos/holodeck/team_simulations.py
  (no output — greenfield)

git ls-files tests/test_ad510_team_simulations.py
  (no output — greenfield)
```
