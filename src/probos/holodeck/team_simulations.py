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
