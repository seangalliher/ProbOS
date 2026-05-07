# AD-539b v1 — Holodeck Scenario Generation from Skill Gaps

**Status:** Drafted, ready for Builder.
**Dependencies:** AD-486 v1 (Wave 99 — Holodeck Birth Chamber substrate), AD-477 v1 (`QualificationHarness` + `QualificationTest` Protocol + `TestResult`), AD-512 v1 (`DiscoveryScenario` + `DiscoveryScenarioRegistry` + 8 default scenarios across 5 capability_categories), AD-539 v1 (`GapReport` + `trigger_qualification_if_needed` pipeline). All shipped at HEAD `6d34fcb`.
**Estimated tests:** ~38 across 6 test classes.

---

## Problem

The AD-539 v1 Knowledge Gap → Qualification Pipeline (shipped 2026-04-XX) detects gaps from four evidence sources (failure clusters, procedure decay, procedure health, episode patterns), classifies them (knowledge / capability / data), maps each to a Skill Framework `mapped_skill_id`, and triggers a qualification path via `skill_service.start_qualification(agent_id, path_id)` for knowledge gaps. What it does NOT do is *generate a Holodeck training scenario* tailored to that gap. The agent therefore knows it has a gap and has a qualification path open, but has no concrete drill to actually execute and close the gap experientially.

Three roadmap surfaces are blocked on AD-539b:

1. **AD-628d-1 — TRAINO Holodeck-driven drill scheduling.** Wave 93 dispatch (`prompts/archive/WAVE-93-DISPATCH.md:55-66`) explicitly parks AD-628d-1 with the forcing function: *"AD-486 + AD-539b ship the Holodeck primitive."* AD-486 shipped in W99; AD-539b is the second-half blocker.
2. **Lab Tech crew role** (`docs/development/roadmap.md:2921`) — *"wait for AD-539b (Holodeck)"*.
3. **AD-510 Team Simulations** scenario-library extensibility — AD-510 inherits the `DiscoveryScenarioRegistry` shape; AD-539b establishes the gap-driven scenario-generation pattern that AD-510 specializes for team scenarios.

The AD-486 Birth Chamber substrate (`src/probos/holodeck/` — `chamber.py`, `phases.py`, `gates.py`, `affect.py`, `scheduler.py`) is now available, AD-477 ships a runnable `QualificationHarness` with `register_test()` + `run_test()` API, and AD-512 ships an 8-scenario `DiscoveryScenarioRegistry` keyed on capability_category. v1 wires these three together with a `GapScenarioGenerator` (gap → DiscoveryScenario) + `HolodeckGapDrill` (DiscoveryScenario + GapReport → QualificationTest Protocol implementation) + `HolodeckGapBridge` (orchestrator that registers the drill with the harness and persists the gap↔scenario↔drill linkage) + a SQLite-backed `HolodeckScenarioStore` mirroring AD-477 `QualificationStore` precedent.

## Solution overview

Six implementation sections, all additive:

- **Section 0:** four new `EventType` values appended to the existing AD-486 Holodeck cluster in `src/probos/events.py:387-393`.
- **Section 1:** new `HolodeckScenarioConfig` Pydantic model in `src/probos/config.py` adjacent to `HolodeckBirthChamberConfig` at `:1756`, plus the field on `SystemConfig` adjacent to `:2796`.
- **Section 2:** new module `src/probos/holodeck/scenarios.py` (~480 LOC) with `ScenarioGapLink`, `ScenarioOutcome`, `GapScenarioGenerator`, `HolodeckGapDrill`, `HolodeckScenarioStore`, `HolodeckGapBridge`.
- **Section 3:** new finalize wirer `_wire_holodeck_scenarios` in `src/probos/startup/finalize.py` adjacent to `_wire_birth_chamber` at `:159` + invocation in main flow alongside `:1543`.
- **Section 4:** optional `holodeck_bridge: Any = None` keyword parameter added to `trigger_qualification_if_needed` in `src/probos/cognitive/gap_predictor.py:474`.
- **Section 5:** public-surface extension of `src/probos/holodeck/__init__.py` (additive imports + `__all__` entries).
- **Section 6:** tracker updates (PROGRESS.md, roadmap.md, decisions-era-4-evolution.md, wave-plan.yaml) + GH issue close.
- **Section 7:** canonical commit message + close paragraph.

---

## Section 0 — New EventTypes

`src/probos/events.py:387-393` currently ends the AD-486 cluster with `HOLODECK_AFFECTIVE_BASELINE_OBSERVED`. Append four new values immediately after, before the `# ── Discovery-Based Capability Building (AD-512) ───` block at `:395`.

### SEARCH

```python
    # AD-486: Holodeck Birth Chamber phase events
    HOLODECK_AGENT_ADMITTED = "holodeck_agent_admitted"
    HOLODECK_PHASE_ENTERED = "holodeck_phase_entered"
    HOLODECK_PHASE_GATE_PASSED = "holodeck_phase_gate_passed"
    HOLODECK_PHASE_GATE_BLOCKED = "holodeck_phase_gate_blocked"
    HOLODECK_GRADUATION = "holodeck_graduation"
    HOLODECK_AFFECTIVE_BASELINE_OBSERVED = "holodeck_affective_baseline_observed"

    # ── Discovery-Based Capability Building (AD-512) ───────────────
```

### REPLACE

```python
    # AD-486: Holodeck Birth Chamber phase events
    HOLODECK_AGENT_ADMITTED = "holodeck_agent_admitted"
    HOLODECK_PHASE_ENTERED = "holodeck_phase_entered"
    HOLODECK_PHASE_GATE_PASSED = "holodeck_phase_gate_passed"
    HOLODECK_PHASE_GATE_BLOCKED = "holodeck_phase_gate_blocked"
    HOLODECK_GRADUATION = "holodeck_graduation"
    HOLODECK_AFFECTIVE_BASELINE_OBSERVED = "holodeck_affective_baseline_observed"

    # AD-539b: Holodeck scenario generation from skill gaps
    HOLODECK_SCENARIO_GENERATED = "holodeck_scenario_generated"
    HOLODECK_SCENARIO_REGISTERED = "holodeck_scenario_registered"
    HOLODECK_SCENARIO_GAP_LINKED = "holodeck_scenario_gap_linked"
    HOLODECK_SCENARIO_OUTCOME_RECORDED = "holodeck_scenario_outcome_recorded"

    # ── Discovery-Based Capability Building (AD-512) ───────────────
```

---

## Section 1 — Pydantic config

### SEARCH (`src/probos/config.py` adjacent to `:1756`)

```python
class HolodeckBirthChamberConfig(BaseModel):
    """AD-486: Holodeck Birth Chamber — graduated cognitive onboarding.

    Default-False per AD-695 transitional-flag precedent: enabling the
    chamber gates Ward Room subscription and proactive-loop dispatch
    behind 5-phase graduation, which is a meaningful behavior change.
    Operators flip ``enabled=True`` after Phase α validation (manual
    cohort under observation).
    """

    enabled: bool = False
    bypass_for_existing_agents: bool = True
    department_order: list[str] = Field(
        default_factory=lambda: [
            "security",
            "operations",
            "engineering",
            "science",
            "medical",
        ]
    )
    calibration_min_episodes: int = Field(default=5, ge=1)
    affective_baseline_check_enabled: bool = True
    auto_advance_enabled: bool = True
    auto_advance_poll_interval_seconds: float = Field(
        default=2.0, ge=0.1, le=30.0
    )
    max_self_discovery_probe_attempts: int = Field(default=3, ge=1)

    @field_validator("department_order")
    @classmethod
    def _department_order_lowercase(cls, v: list[str]) -> list[str]:
        return [d.lower() for d in v]


class NamingConfig(BaseModel):
```

### REPLACE

```python
class HolodeckBirthChamberConfig(BaseModel):
    """AD-486: Holodeck Birth Chamber — graduated cognitive onboarding.

    Default-False per AD-695 transitional-flag precedent: enabling the
    chamber gates Ward Room subscription and proactive-loop dispatch
    behind 5-phase graduation, which is a meaningful behavior change.
    Operators flip ``enabled=True`` after Phase α validation (manual
    cohort under observation).
    """

    enabled: bool = False
    bypass_for_existing_agents: bool = True
    department_order: list[str] = Field(
        default_factory=lambda: [
            "security",
            "operations",
            "engineering",
            "science",
            "medical",
        ]
    )
    calibration_min_episodes: int = Field(default=5, ge=1)
    affective_baseline_check_enabled: bool = True
    auto_advance_enabled: bool = True
    auto_advance_poll_interval_seconds: float = Field(
        default=2.0, ge=0.1, le=30.0
    )
    max_self_discovery_probe_attempts: int = Field(default=3, ge=1)

    @field_validator("department_order")
    @classmethod
    def _department_order_lowercase(cls, v: list[str]) -> list[str]:
        return [d.lower() for d in v]


class HolodeckScenarioConfig(BaseModel):
    """AD-539b: Holodeck scenario generation from skill gaps.

    Default-False per AD-695 transitional-flag precedent: enabling the
    bridge causes ``HolodeckGapBridge.bridge_gap_to_holodeck`` to
    register a runnable ``HolodeckGapDrill`` with the AD-477
    ``QualificationHarness`` for every classified knowledge gap that
    has a ``mapped_skill_id``. v1 ships dormant — operators flip
    ``enabled=True`` once an AD-486 cohort produces real ``GapReport``
    instances with non-empty ``mapped_skill_id`` to bridge against.
    """

    enabled: bool = False
    auto_register_with_harness: bool = True
    default_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    default_tier: int = Field(default=2, ge=1, le=3)
    category_fallback: str = "construction"
    persist_to_sqlite: bool = False
    data_subdir: str = "holodeck_scenarios"


class NamingConfig(BaseModel):
```

### SEARCH (`src/probos/config.py` adjacent to `:2796`)

```python
    holodeck_birth_chamber: HolodeckBirthChamberConfig = HolodeckBirthChamberConfig()
```

### REPLACE

```python
    holodeck_birth_chamber: HolodeckBirthChamberConfig = HolodeckBirthChamberConfig()
    holodeck_scenarios: HolodeckScenarioConfig = HolodeckScenarioConfig()
```

---

## Section 2 — `src/probos/holodeck/scenarios.py` (new file)

Create the file with the full content below. Single-Responsibility Principle: scenario generation, drill adaptation, store, bridge — each is a separate class within one cohesive module.

```python
"""AD-539b v1 — Holodeck Scenario Generation from Skill Gaps.

Bridges the AD-539 ``GapReport`` pipeline to the AD-486 Holodeck substrate
via the AD-477 ``QualificationHarness`` runnable surface. Reuses the
AD-512 ``DiscoveryScenarioRegistry`` 8-scenario default catalog for
category matching; falls back to a templated scenario when no match
exists.

Public API:
    GapScenarioGenerator:
        generate_from_gap(gap, *, registry=None) -> DiscoveryScenario
    HolodeckGapDrill:
        Implements probos.cognitive.qualification.QualificationTest Protocol.
        async run(agent_id, runtime) -> TestResult
    HolodeckScenarioStore:
        async start() / async stop()
        async save_link(link) / async get_link_for_gap(gap_id)
        async update_outcome(gap_id, outcome)
    HolodeckGapBridge:
        async bridge_gap_to_holodeck(gap) -> ScenarioGapLink | None

Forcing-function deferrals (not v1):
- AD-539b-d: ZPDCalibrator-driven difficulty calibration
  (forcing function: runtime.zpd_calibrator accumulates >=10 outcomes
  per agent under enabled=True)
- AD-539b-e: Auto-schedule generated drills via AD-628d DrillCalendar
  (forcing function: AD-628d-1 drafted AND first 5 generated drills
  manually scheduled).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from probos.events import EventType

if TYPE_CHECKING:
    from probos.cognitive.gap_predictor import GapReport
    from probos.cognitive.qualification import (
        QualificationHarness,
        TestResult,
    )
    from probos.crew_development.discovery.scenarios import (
        DiscoveryScenario,
        DiscoveryScenarioRegistry,
    )

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Frozen dataclasses — defaulted fields AFTER non-defaulted (W5 conv #6).
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class ScenarioGapLink:
    """Persistent link between a GapReport and its generated scenario+drill."""

    gap_id: str
    scenario_id: str
    drill_test_name: str
    agent_id: str
    generated_at: float
    status: str = "generated"  # "generated" | "registered" | "executed" | "closed"
    last_run_score: float | None = None
    last_run_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "scenario_id": self.scenario_id,
            "drill_test_name": self.drill_test_name,
            "agent_id": self.agent_id,
            "generated_at": self.generated_at,
            "status": self.status,
            "last_run_score": self.last_run_score,
            "last_run_at": self.last_run_at,
        }


@dataclass(frozen=True)
class ScenarioOutcome:
    """Snapshot of a single drill execution for a linked gap."""

    link: ScenarioGapLink
    score: float
    passed: bool
    timestamp: float
    notes: str = ""


# ----------------------------------------------------------------------
# Intent → category mapping. Reuses AD-512's 5 capability categories.
# ----------------------------------------------------------------------

_INTENT_CATEGORY_HINTS: dict[str, str] = {
    # diagnosis-flavored
    "diagnose": "diagnosis", "investigate": "diagnosis", "inspect": "diagnosis",
    "isolate_fault": "diagnosis", "system_health": "diagnosis",
    # analysis-flavored
    "analyze": "analysis", "evaluate": "analysis", "assess": "analysis",
    "trend": "analysis", "report": "analysis",
    # communication-flavored
    "summarize": "communication", "brief": "communication", "explain": "communication",
    "translate": "communication", "compose": "communication",
    # coordination-flavored
    "coordinate": "coordination", "delegate": "coordination", "handoff": "coordination",
    "schedule": "coordination", "assign": "coordination",
    # construction-flavored
    "build": "construction", "construct": "construction", "design": "construction",
    "plan": "construction", "remediate": "construction", "duty_execution": "construction",
}


def _category_from_intent(intent: str) -> str | None:
    """Return capability_category for an intent or its prefix, or None."""
    intent = (intent or "").lower()
    if not intent:
        return None
    if intent in _INTENT_CATEGORY_HINTS:
        return _INTENT_CATEGORY_HINTS[intent]
    for prefix, cat in _INTENT_CATEGORY_HINTS.items():
        if intent.startswith(prefix):
            return cat
    return None


# ----------------------------------------------------------------------
# GapScenarioGenerator
# ----------------------------------------------------------------------

class GapScenarioGenerator:
    """Translates a ``GapReport`` into a ``DiscoveryScenario``.

    Strategy:
    1. Map gap.affected_intent_types[0] (or gap.mapped_skill_id) to a
       capability_category via the _INTENT_CATEGORY_HINTS table.
    2. If a registry is supplied, call list_by_category(cat) and pick the
       lowest-difficulty scenario (gap-driven drills should start
       gentle).
    3. If no match, synthesize a templated DiscoveryScenario whose
       scenario_id is derived from gap.id and whose capability_category
       falls back to config.category_fallback.
    """

    def __init__(self, *, category_fallback: str = "construction") -> None:
        self._category_fallback = category_fallback

    def generate_from_gap(
        self,
        gap: "GapReport",
        *,
        registry: "DiscoveryScenarioRegistry | None" = None,
    ) -> "DiscoveryScenario":
        from probos.crew_development.discovery.scenarios import DiscoveryScenario

        # 1. derive category
        category = self._derive_category(gap)

        # 2. registry match
        if registry is not None and category is not None:
            try:
                matches = registry.list_by_category(category)
            except Exception:
                logger.warning(
                    "AD-539b: registry.list_by_category raised for %s; "
                    "falling back to template", category, exc_info=True,
                )
                matches = ()
            if matches:
                # lowest-difficulty match (gentle entry per Vygotsky ZPD spirit;
                # AD-539b-d will calibrate against agent confidence later)
                return min(matches, key=lambda s: s.difficulty)

        # 3. template fallback
        return self._templated_scenario(gap, category)

    def _derive_category(self, gap: "GapReport") -> str | None:
        # Prefer the first affected intent_type; fall back to mapped_skill_id
        for intent in gap.affected_intent_types:
            cat = _category_from_intent(intent)
            if cat:
                return cat
        if gap.mapped_skill_id:
            return _category_from_intent(gap.mapped_skill_id)
        return None

    def _templated_scenario(
        self, gap: "GapReport", category: str | None,
    ) -> "DiscoveryScenario":
        from probos.crew_development.discovery.scenarios import DiscoveryScenario

        cat = category or self._category_fallback
        sid = f"gap_drill:{gap.id}"
        # Difficulty derived from priority — high/critical = harder (more rigorous probe)
        diff_by_priority = {"low": 0.30, "medium": 0.45, "high": 0.60, "critical": 0.70}
        difficulty = diff_by_priority.get(gap.priority, 0.45)
        return DiscoveryScenario(
            scenario_id=sid,
            title=f"Gap-driven drill: {gap.description[:60]}",
            capability_category=cat,
            summary=(
                f"Practice scenario synthesized from gap {gap.id}. "
                f"Targets skill {gap.mapped_skill_id or '(unmapped)'} "
                f"and intent types {', '.join(gap.affected_intent_types) or '(none)'}."
            ),
            learning_objectives=(
                f"Demonstrate competency on {gap.mapped_skill_id or 'target skill'}",
                "Articulate the cause of the original gap evidence",
                "Produce a remediation aligned with Standing Orders",
            ),
            difficulty=difficulty,
            scaffolding_level="medium",
        )


# ----------------------------------------------------------------------
# HolodeckGapDrill — implements QualificationTest Protocol (AD-477)
# ----------------------------------------------------------------------

DrillRunner = Callable[
    ["DiscoveryScenario", "GapReport", str, Any],
    Any,  # awaitable returning a TestResult or a (score:float, passed:bool, details:dict) tuple
]


class HolodeckGapDrill:
    """Adapts a (DiscoveryScenario, GapReport) pair to the AD-477
    ``QualificationTest`` Protocol shape.

    The harness invokes ``run(agent_id, runtime)`` and persists the
    resulting ``TestResult``. The bridge separately records the link
    in ``HolodeckScenarioStore``.
    """

    def __init__(
        self,
        *,
        scenario: "DiscoveryScenario",
        gap: "GapReport",
        threshold: float = 0.6,
        tier: int = 2,
        drill_runner: DrillRunner | None = None,
    ) -> None:
        self._scenario = scenario
        self._gap = gap
        self._threshold = threshold
        self._tier = tier
        self._drill_runner = drill_runner

    @property
    def name(self) -> str:
        return f"holodeck_gap:{self._gap.id}"

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
    def scenario(self) -> "DiscoveryScenario":
        return self._scenario

    @property
    def gap(self) -> "GapReport":
        return self._gap

    async def run(self, agent_id: str, runtime: Any) -> "TestResult":
        from probos.cognitive.qualification import TestResult

        t0 = time.time()
        if self._drill_runner is None:
            # v1 default: NoOp drill — declares the scenario "presented" with a
            # neutral 0.5 score. Real runners will be supplied by AD-628d-1 /
            # AD-486e Construct API consumers.
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
                    "gap_id": self._gap.id,
                    "noop": True,
                    "note": "AD-539b v1 default drill_runner — supply runner via bridge",
                },
            )
        try:
            result = await self._drill_runner(
                self._scenario, self._gap, agent_id, runtime,
            )
        except Exception as exc:
            logger.warning(
                "AD-539b: drill_runner raised for %s/%s: %s",
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
                    "gap_id": self._gap.id,
                },
            )
        # If the runner returned a TestResult, pass through
        if isinstance(result, TestResult):
            return result
        # Otherwise expect (score, passed, details) tuple
        try:
            score, passed, details = result
        except Exception:
            logger.warning(
                "AD-539b: drill_runner returned malformed result for %s; "
                "treating as failure", self.name,
            )
            return TestResult(
                agent_id=agent_id, test_name=self.name, tier=self._tier,
                score=0.0, passed=False, timestamp=time.time(),
                duration_ms=(time.time() - t0) * 1000,
                error="malformed drill_runner result",
            )
        merged_details = {
            "scenario_id": self._scenario.scenario_id,
            "gap_id": self._gap.id,
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
# HolodeckScenarioStore — SQLite via ConnectionFactory + in-memory fallback
# ----------------------------------------------------------------------

_STORE_SCHEMA = """\
CREATE TABLE IF NOT EXISTS scenario_gap_links (
    gap_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    drill_test_name TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    generated_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'generated',
    last_run_score REAL,
    last_run_at REAL
);

CREATE INDEX IF NOT EXISTS idx_links_agent ON scenario_gap_links(agent_id);
CREATE INDEX IF NOT EXISTS idx_links_scenario ON scenario_gap_links(scenario_id);
"""


class HolodeckScenarioStore:
    """Persists ``ScenarioGapLink`` records.

    Mirrors AD-477 ``QualificationStore`` shape: SQLite via the existing
    ``probos.storage.sqlite_factory.default_factory`` ConnectionFactory.
    Falls back to in-memory dict when ``data_dir`` is ``None``.
    """

    def __init__(
        self,
        data_dir: str | Path | None = None,
        connection_factory: Any = None,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else None
        self._connection_factory = connection_factory
        self._db: Any = None
        self._memory: dict[str, ScenarioGapLink] = {}

    async def start(self) -> None:
        if self._data_dir is None:
            return
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
        db_path = str(self._data_dir / "holodeck_scenarios.db")
        self._db = await self._connection_factory.connect(db_path)
        await self._db.executescript(_STORE_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        if self._db is not None:
            try:
                await self._db.close()
            except Exception:
                pass
            self._db = None

    async def save_link(self, link: ScenarioGapLink) -> None:
        self._memory[link.gap_id] = link
        if self._db is None:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO scenario_gap_links "
            "(gap_id, scenario_id, drill_test_name, agent_id, generated_at, "
            " status, last_run_score, last_run_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (link.gap_id, link.scenario_id, link.drill_test_name,
             link.agent_id, link.generated_at, link.status,
             link.last_run_score, link.last_run_at),
        )
        await self._db.commit()

    async def get_link_for_gap(self, gap_id: str) -> ScenarioGapLink | None:
        if gap_id in self._memory:
            return self._memory[gap_id]
        if self._db is None:
            return None
        cur = await self._db.execute(
            "SELECT gap_id, scenario_id, drill_test_name, agent_id, "
            "generated_at, status, last_run_score, last_run_at "
            "FROM scenario_gap_links WHERE gap_id = ?",
            (gap_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        link = ScenarioGapLink(
            gap_id=row[0], scenario_id=row[1], drill_test_name=row[2],
            agent_id=row[3], generated_at=row[4], status=row[5],
            last_run_score=row[6], last_run_at=row[7],
        )
        self._memory[gap_id] = link
        return link

    async def update_outcome(self, gap_id: str, outcome: ScenarioOutcome) -> None:
        existing = await self.get_link_for_gap(gap_id)
        if existing is None:
            return
        new_status = "executed" if not outcome.passed else "closed"
        updated = replace(
            existing,
            status=new_status,
            last_run_score=outcome.score,
            last_run_at=outcome.timestamp,
        )
        await self.save_link(updated)


# ----------------------------------------------------------------------
# HolodeckGapBridge — orchestrator
# ----------------------------------------------------------------------

class HolodeckGapBridge:
    """Generates a scenario from a ``GapReport``, registers a runnable
    ``HolodeckGapDrill`` with the AD-477 ``QualificationHarness``, and
    persists the link in ``HolodeckScenarioStore``.

    Idempotent: if a link already exists for ``gap.id``, returns the
    existing link without re-registering.
    """

    def __init__(
        self,
        *,
        config: Any,
        generator: GapScenarioGenerator,
        store: HolodeckScenarioStore,
        emit_event_fn: Callable[..., None] | None = None,
        qualification_harness: "QualificationHarness | None" = None,
        scenario_registry: "DiscoveryScenarioRegistry | None" = None,
        drill_runner: DrillRunner | None = None,
    ) -> None:
        self._config = config
        self._generator = generator
        self._store = store
        self._emit_event_fn = emit_event_fn
        self._qualification_harness = qualification_harness
        self._scenario_registry = scenario_registry
        self._drill_runner = drill_runner

    # ── Late-bind setters (Wave 5 conv #5) ──────────────────────────
    def set_qualification_harness(self, harness: "QualificationHarness") -> None:
        self._qualification_harness = harness

    def set_scenario_registry(self, registry: "DiscoveryScenarioRegistry") -> None:
        self._scenario_registry = registry

    def set_drill_runner(self, runner: DrillRunner) -> None:
        self._drill_runner = runner

    @property
    def qualification_harness(self) -> "QualificationHarness | None":
        return self._qualification_harness

    @property
    def scenario_registry(self) -> "DiscoveryScenarioRegistry | None":
        return self._scenario_registry

    # ── Public API ──────────────────────────────────────────────────

    async def bridge_gap_to_holodeck(
        self, gap: "GapReport",
    ) -> ScenarioGapLink | None:
        """Generate scenario + register drill + persist link.

        Returns the link, or None if the gap is not eligible (e.g. no
        mapped_skill_id, gap_type=capability/data, or bridge disabled).
        """
        if not getattr(self._config, "enabled", False):
            return None
        # capability and data gaps are not knowledge-skill gaps; mirror
        # AD-539 trigger_qualification_if_needed gating
        if gap.gap_type in ("capability", "data"):
            return None
        if not gap.mapped_skill_id:
            return None

        # Idempotency
        existing = await self._store.get_link_for_gap(gap.id)
        if existing is not None:
            return existing

        # 1. Generate scenario
        scenario = self._generator.generate_from_gap(
            gap, registry=self._scenario_registry,
        )
        self._emit(EventType.HOLODECK_SCENARIO_GENERATED, {
            "gap_id": gap.id,
            "scenario_id": scenario.scenario_id,
            "capability_category": scenario.capability_category,
            "agent_id": gap.agent_id,
        })

        # 2. Build drill
        drill = HolodeckGapDrill(
            scenario=scenario,
            gap=gap,
            threshold=getattr(self._config, "default_threshold", 0.6),
            tier=getattr(self._config, "default_tier", 2),
            drill_runner=self._drill_runner,
        )

        # 3. Register with harness if configured
        registered = False
        if (
            self._qualification_harness is not None
            and getattr(self._config, "auto_register_with_harness", True)
        ):
            try:
                self._qualification_harness.register_test(drill)
                registered = True
                self._emit(EventType.HOLODECK_SCENARIO_REGISTERED, {
                    "gap_id": gap.id,
                    "scenario_id": scenario.scenario_id,
                    "drill_test_name": drill.name,
                    "agent_id": gap.agent_id,
                })
            except Exception:
                logger.warning(
                    "AD-539b: harness.register_test raised for %s; "
                    "drill not registered", drill.name, exc_info=True,
                )

        # 4. Persist link
        link = ScenarioGapLink(
            gap_id=gap.id,
            scenario_id=scenario.scenario_id,
            drill_test_name=drill.name,
            agent_id=gap.agent_id,
            generated_at=time.time(),
            status="registered" if registered else "generated",
        )
        await self._store.save_link(link)
        self._emit(EventType.HOLODECK_SCENARIO_GAP_LINKED, {
            "gap_id": gap.id,
            "scenario_id": scenario.scenario_id,
            "drill_test_name": drill.name,
            "agent_id": gap.agent_id,
            "status": link.status,
        })

        # 5. Back-fill qualification_path_id so AD-539 closure tracking
        #    has a reference. Mutates the gap in place; AD-539 GapReport
        #    is a non-frozen dataclass.
        if not gap.qualification_path_id:
            gap.qualification_path_id = drill.name

        return link

    async def record_outcome(
        self, gap_id: str, outcome: ScenarioOutcome,
    ) -> None:
        await self._store.update_outcome(gap_id, outcome)
        self._emit(EventType.HOLODECK_SCENARIO_OUTCOME_RECORDED, {
            "gap_id": gap_id,
            "score": outcome.score,
            "passed": outcome.passed,
        })

    # ── Helpers ─────────────────────────────────────────────────────

    def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        if self._emit_event_fn is None:
            return
        try:
            self._emit_event_fn(event_type, payload)
        except Exception:
            logger.warning(
                "AD-539b: emit_event_fn raised for %s", event_type.value,
                exc_info=True,
            )
```

---

## Section 3 — Finalize wirer

### SEARCH (`src/probos/startup/finalize.py` adjacent to `:241`)

```python
def _wire_discovery_learning(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-512 v1: Wire DiscoveryScenarioRegistry, StrengthMap,
    CapabilityConfidenceScorer, and ZPDCalibrator (observational substrate).
    """
```

### REPLACE

```python
def _wire_holodeck_scenarios(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-539b v1: Wire HolodeckGapBridge — gap-driven scenario generation.

    Default-False per AD-695 transitional-flag precedent. When disabled,
    no bridge is constructed; ``runtime.holodeck_gap_bridge`` is not set
    and AD-539 ``trigger_qualification_if_needed`` continues to run with
    its default ``holodeck_bridge=None`` behavior (byte-for-byte
    identical to pre-AD-539b semantics).
    """
    cfg = getattr(config, "holodeck_scenarios", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.holodeck.scenarios import (
        GapScenarioGenerator,
        HolodeckGapBridge,
        HolodeckScenarioStore,
    )

    emit_fn = getattr(runtime, "emit_event", None)

    data_dir: Any = None
    if cfg.persist_to_sqlite:
        ship_data_dir = getattr(runtime, "data_dir", None)
        if ship_data_dir is not None:
            from pathlib import Path as _Path
            data_dir = _Path(ship_data_dir) / cfg.data_subdir
            data_dir.mkdir(parents=True, exist_ok=True)

    generator = GapScenarioGenerator(category_fallback=cfg.category_fallback)
    store = HolodeckScenarioStore(data_dir=data_dir)

    bridge = HolodeckGapBridge(
        config=cfg,
        generator=generator,
        store=store,
        emit_event_fn=emit_fn,
        qualification_harness=getattr(runtime, "qualification_harness", None),
        scenario_registry=getattr(runtime, "discovery_scenario_registry", None),
    )
    runtime.holodeck_gap_bridge = bridge  # public attr (Wave 5 conv #1)

    logger.info(
        "AD-539b: Holodeck scenario generation v1 initialized "
        "(harness=%s, registry=%s, persist=%s)",
        bridge.qualification_harness is not None,
        bridge.scenario_registry is not None,
        cfg.persist_to_sqlite,
    )
    return True


def _wire_discovery_learning(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-512 v1: Wire DiscoveryScenarioRegistry, StrengthMap,
    CapabilityConfidenceScorer, and ZPDCalibrator (observational substrate).
    """
```

### SEARCH (`src/probos/startup/finalize.py` adjacent to `:1543`)

```python
    if _wire_birth_chamber(runtime=runtime, config=config):
```

### REPLACE

```python
    if _wire_birth_chamber(runtime=runtime, config=config):
        pass
    if _wire_holodeck_scenarios(runtime=runtime, config=config):
```

(NB: the existing `_wire_birth_chamber` invocation may already be inside an `if`/conditional block — the Builder must read `:1543`'s actual surrounding context first and place the new invocation immediately AFTER the `_wire_birth_chamber` call site, preserving the existing invocation pattern. The SEARCH/REPLACE above is a guideline; if the existing pattern is `if X: ...`, the new invocation lands as a sibling `if Y: ...` immediately below. AD-512's `_wire_discovery_learning` invocation is the closest precedent — invoked once in the main flow without grouping.)

---

## Section 4 — Optional `holodeck_bridge` keyword on `trigger_qualification_if_needed`

### SEARCH (`src/probos/cognitive/gap_predictor.py:474`)

```python
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
```

### REPLACE

```python
async def trigger_qualification_if_needed(
    gap: GapReport,
    skill_service: Any,
    *,
    holodeck_bridge: Any = None,
) -> GapReport:
    """If the gap reveals proficiency below target, start a qualification path.

    AD-539b: when ``holodeck_bridge`` is supplied (typically
    ``runtime.holodeck_gap_bridge`` from the AD-539b wirer), also call
    ``holodeck_bridge.bridge_gap_to_holodeck(gap)`` AFTER the existing
    skill-service path. The bridge is idempotent against gap.id, so
    multiple invocations are safe. Errors are logged-and-degraded —
    failure to bridge does NOT propagate.
    """
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
        else:
            # Start new qualification
            await skill_service.start_qualification(gap.agent_id, path_id)
            gap.qualification_path_id = path_id
    except Exception:
        pass

    # AD-539b: optional Holodeck-scenario bridging
    if holodeck_bridge is not None:
        try:
            await holodeck_bridge.bridge_gap_to_holodeck(gap)
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "AD-539b: holodeck_bridge.bridge_gap_to_holodeck raised for "
                "gap %s; continuing without scenario", gap.id, exc_info=True,
            )

    return gap
```

---

## Section 5 — Public-surface extension of `holodeck/__init__.py`

### SEARCH (`src/probos/holodeck/__init__.py`)

```python
from probos.holodeck.affect import (
    AffectiveBaselineCheck,
    AffectiveObservation,
    NoOpAffectiveBaselineCheck,
)
from probos.holodeck.chamber import BirthChamber, BirthChamberRecord
from probos.holodeck.phases import HolodeckPhase
from probos.holodeck.scheduler import DepartmentActivationScheduler

__all__ = [
    "AffectiveBaselineCheck",
    "AffectiveObservation",
    "BirthChamber",
    "BirthChamberRecord",
    "DepartmentActivationScheduler",
    "HolodeckPhase",
    "NoOpAffectiveBaselineCheck",
]
```

### REPLACE

```python
from probos.holodeck.affect import (
    AffectiveBaselineCheck,
    AffectiveObservation,
    NoOpAffectiveBaselineCheck,
)
from probos.holodeck.chamber import BirthChamber, BirthChamberRecord
from probos.holodeck.phases import HolodeckPhase
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
```

---

## Tests — `tests/test_ad539b_holodeck_scenarios.py` (~38 tests, 6 classes)

Skeleton to be filled in by Builder. Use real `Config()`, real `BaseModel`, real `GapReport` instances; stub only `QualificationHarness` (use `MagicMock(spec=QualificationHarness)` so Protocol-shape is enforced) and `DiscoveryScenarioRegistry` (real instance with default catalog).

```python
"""AD-539b v1 — Holodeck scenario generation from skill gaps."""

import time
import pytest
from unittest.mock import MagicMock

from probos.cognitive.gap_predictor import GapReport, trigger_qualification_if_needed
from probos.cognitive.qualification import QualificationHarness, QualificationStore, TestResult, QualificationTest
from probos.config import HolodeckScenarioConfig, SystemConfig
from probos.crew_development.discovery.scenarios import (
    DiscoveryScenario,
    DiscoveryScenarioRegistry,
)
from probos.events import EventType
from probos.holodeck.scenarios import (
    GapScenarioGenerator,
    HolodeckGapBridge,
    HolodeckGapDrill,
    HolodeckScenarioStore,
    ScenarioGapLink,
    ScenarioOutcome,
)


# ---------------------------------------------------------------------
# 0. EventTypes
# ---------------------------------------------------------------------

class TestEventTypes:
    def test_scenario_generated_value(self):
        assert EventType.HOLODECK_SCENARIO_GENERATED.value == "holodeck_scenario_generated"

    def test_scenario_registered_value(self):
        assert EventType.HOLODECK_SCENARIO_REGISTERED.value == "holodeck_scenario_registered"

    def test_scenario_gap_linked_value(self):
        assert EventType.HOLODECK_SCENARIO_GAP_LINKED.value == "holodeck_scenario_gap_linked"

    def test_scenario_outcome_recorded_value(self):
        assert EventType.HOLODECK_SCENARIO_OUTCOME_RECORDED.value == "holodeck_scenario_outcome_recorded"


# ---------------------------------------------------------------------
# 1. Config
# ---------------------------------------------------------------------

class TestConfig:
    def test_defaults(self):
        cfg = HolodeckScenarioConfig()
        assert cfg.enabled is False
        assert cfg.auto_register_with_harness is True
        assert cfg.default_threshold == 0.6
        assert cfg.default_tier == 2
        assert cfg.category_fallback == "construction"

    def test_threshold_bounds(self):
        with pytest.raises(Exception):
            HolodeckScenarioConfig(default_threshold=1.5)

    def test_tier_bounds(self):
        with pytest.raises(Exception):
            HolodeckScenarioConfig(default_tier=5)

    def test_system_config_field(self):
        sc = SystemConfig()
        assert isinstance(sc.holodeck_scenarios, HolodeckScenarioConfig)
        assert sc.holodeck_scenarios.enabled is False

    def test_persist_default_off(self):
        assert HolodeckScenarioConfig().persist_to_sqlite is False


# ---------------------------------------------------------------------
# 2. ScenarioGapLink
# ---------------------------------------------------------------------

class TestScenarioGapLink:
    def test_frozen(self):
        link = ScenarioGapLink(gap_id="g1", scenario_id="s1", drill_test_name="d1",
                               agent_id="a1", generated_at=1.0)
        with pytest.raises(Exception):
            link.gap_id = "g2"  # type: ignore

    def test_default_status_generated(self):
        link = ScenarioGapLink(gap_id="g1", scenario_id="s1", drill_test_name="d1",
                               agent_id="a1", generated_at=1.0)
        assert link.status == "generated"
        assert link.last_run_score is None

    def test_to_dict_roundtrip(self):
        link = ScenarioGapLink(gap_id="g1", scenario_id="s1", drill_test_name="d1",
                               agent_id="a1", generated_at=1.0,
                               status="executed", last_run_score=0.8, last_run_at=2.0)
        d = link.to_dict()
        assert d["status"] == "executed"
        assert d["last_run_score"] == 0.8

    def test_field_order_defaults_after_required(self):
        # Required fields first
        link = ScenarioGapLink("g", "s", "d", "a", 1.0)
        assert link.status == "generated"


# ---------------------------------------------------------------------
# 3. GapScenarioGenerator
# ---------------------------------------------------------------------

def _make_gap(**overrides):
    defaults = dict(
        id="gap:test:abc", agent_id="agent-1", agent_type="science",
        gap_type="knowledge", description="Lacks diagnose ability",
        evidence_sources=["episode:low_confidence"],
        affected_intent_types=["diagnose"], failure_rate=0.5,
        episode_count=5, mapped_skill_id="diagnose", current_proficiency=1,
        target_proficiency=3, priority="medium",
    )
    defaults.update(overrides)
    return GapReport(**defaults)


class TestGapScenarioGenerator:
    def test_no_registry_no_match_returns_template(self):
        gen = GapScenarioGenerator()
        gap = _make_gap(affected_intent_types=["xyz_unknown"], mapped_skill_id="")
        scen = gen.generate_from_gap(gap)
        assert scen.scenario_id == f"gap_drill:{gap.id}"

    def test_registry_match_diagnosis_category(self):
        gen = GapScenarioGenerator()
        reg = DiscoveryScenarioRegistry()
        gap = _make_gap(affected_intent_types=["diagnose"])
        scen = gen.generate_from_gap(gap, registry=reg)
        assert scen.capability_category == "diagnosis"

    def test_registry_match_picks_lowest_difficulty(self):
        gen = GapScenarioGenerator()
        reg = DiscoveryScenarioRegistry()
        gap = _make_gap(affected_intent_types=["diagnose"])
        scen = gen.generate_from_gap(gap, registry=reg)
        all_diag = reg.list_by_category("diagnosis")
        assert scen.difficulty == min(s.difficulty for s in all_diag)

    def test_template_uses_priority_difficulty(self):
        gen = GapScenarioGenerator()
        gap_high = _make_gap(affected_intent_types=["unknown"], priority="critical")
        scen = gen.generate_from_gap(gap_high)
        assert scen.difficulty == 0.70

    def test_intent_prefix_matching(self):
        gen = GapScenarioGenerator()
        reg = DiscoveryScenarioRegistry()
        gap = _make_gap(affected_intent_types=["analyze_telemetry"])
        scen = gen.generate_from_gap(gap, registry=reg)
        assert scen.capability_category == "analysis"

    def test_falls_back_via_mapped_skill_id(self):
        gen = GapScenarioGenerator()
        reg = DiscoveryScenarioRegistry()
        gap = _make_gap(affected_intent_types=[], mapped_skill_id="coordinate")
        scen = gen.generate_from_gap(gap, registry=reg)
        assert scen.capability_category == "coordination"

    def test_category_fallback_used(self):
        gen = GapScenarioGenerator(category_fallback="analysis")
        gap = _make_gap(affected_intent_types=["unknown"], mapped_skill_id="unknown_skill")
        scen = gen.generate_from_gap(gap)
        assert scen.capability_category == "analysis"

    def test_template_scenario_id_format(self):
        gen = GapScenarioGenerator()
        gap = _make_gap(affected_intent_types=["unknown"])
        scen = gen.generate_from_gap(gap)
        assert scen.scenario_id == f"gap_drill:{gap.id}"


# ---------------------------------------------------------------------
# 4. HolodeckGapDrill (QualificationTest Protocol)
# ---------------------------------------------------------------------

class TestHolodeckGapDrill:
    def _make_drill(self, **kwargs):
        scen = DiscoveryScenario(
            scenario_id="s1", title="t", capability_category="diagnosis",
            summary="sum", learning_objectives=("lo1",), difficulty=0.4,
            scaffolding_level="medium",
        )
        gap = _make_gap()
        return HolodeckGapDrill(scenario=scen, gap=gap, **kwargs)

    def test_implements_protocol(self):
        d = self._make_drill()
        assert isinstance(d, QualificationTest)

    def test_name_format(self):
        d = self._make_drill()
        assert d.name == "holodeck_gap:gap:test:abc"

    def test_threshold_default(self):
        d = self._make_drill(threshold=0.7)
        assert d.threshold == 0.7

    def test_tier_default(self):
        d = self._make_drill()
        assert d.tier == 2

    @pytest.mark.asyncio
    async def test_run_noop_returns_neutral(self):
        d = self._make_drill()
        result = await d.run("agent-1", runtime=None)
        assert isinstance(result, TestResult)
        assert result.score == 0.5
        assert result.passed is False
        assert result.details["noop"] is True

    @pytest.mark.asyncio
    async def test_run_with_runner_tuple(self):
        async def runner(scen, gap, agent_id, runtime):
            return (0.9, True, {"k": "v"})
        d = self._make_drill(drill_runner=runner)
        result = await d.run("agent-1", runtime=None)
        assert result.score == 0.9
        assert result.passed is True
        assert result.details["k"] == "v"


# ---------------------------------------------------------------------
# 5. HolodeckGapBridge
# ---------------------------------------------------------------------

class TestHolodeckGapBridge:
    def _make_bridge(self, *, enabled=True, harness=None, registry=None,
                     emit_calls=None):
        cfg = HolodeckScenarioConfig(enabled=enabled)
        gen = GapScenarioGenerator()
        store = HolodeckScenarioStore()
        emit = (lambda et, p: emit_calls.append((et, p))) if emit_calls is not None else None
        return HolodeckGapBridge(
            config=cfg, generator=gen, store=store,
            emit_event_fn=emit, qualification_harness=harness,
            scenario_registry=registry,
        )

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self):
        b = self._make_bridge(enabled=False)
        gap = _make_gap()
        assert await b.bridge_gap_to_holodeck(gap) is None

    @pytest.mark.asyncio
    async def test_capability_gap_skipped(self):
        b = self._make_bridge()
        gap = _make_gap(gap_type="capability")
        assert await b.bridge_gap_to_holodeck(gap) is None

    @pytest.mark.asyncio
    async def test_no_mapped_skill_skipped(self):
        b = self._make_bridge()
        gap = _make_gap(mapped_skill_id="")
        assert await b.bridge_gap_to_holodeck(gap) is None

    @pytest.mark.asyncio
    async def test_idempotent_returns_existing(self):
        b = self._make_bridge()
        gap = _make_gap()
        first = await b.bridge_gap_to_holodeck(gap)
        second = await b.bridge_gap_to_holodeck(gap)
        assert first is not None
        assert first.gap_id == second.gap_id
        assert first.generated_at == second.generated_at

    @pytest.mark.asyncio
    async def test_registers_with_harness(self):
        harness = MagicMock(spec=QualificationHarness)
        b = self._make_bridge(harness=harness)
        gap = _make_gap()
        link = await b.bridge_gap_to_holodeck(gap)
        assert link is not None
        assert link.status == "registered"
        harness.register_test.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_harness_status_generated(self):
        b = self._make_bridge(harness=None)
        gap = _make_gap()
        link = await b.bridge_gap_to_holodeck(gap)
        assert link is not None
        assert link.status == "generated"

    @pytest.mark.asyncio
    async def test_emits_three_events(self):
        emit_calls: list = []
        harness = MagicMock(spec=QualificationHarness)
        b = self._make_bridge(harness=harness, emit_calls=emit_calls)
        gap = _make_gap()
        await b.bridge_gap_to_holodeck(gap)
        types = [c[0] for c in emit_calls]
        assert EventType.HOLODECK_SCENARIO_GENERATED in types
        assert EventType.HOLODECK_SCENARIO_REGISTERED in types
        assert EventType.HOLODECK_SCENARIO_GAP_LINKED in types

    @pytest.mark.asyncio
    async def test_back_fills_qualification_path_id(self):
        b = self._make_bridge()
        gap = _make_gap()
        assert gap.qualification_path_id == ""
        await b.bridge_gap_to_holodeck(gap)
        assert gap.qualification_path_id == f"holodeck_gap:{gap.id}"


# ---------------------------------------------------------------------
# 6. Startup wiring
# ---------------------------------------------------------------------

class TestStartupWiring:
    def test_disabled_returns_false(self):
        from probos.startup.finalize import _wire_holodeck_scenarios
        runtime = MagicMock()
        config = MagicMock()
        config.holodeck_scenarios = HolodeckScenarioConfig(enabled=False)
        assert _wire_holodeck_scenarios(runtime=runtime, config=config) is False
        assert not hasattr(runtime, "holodeck_gap_bridge") or runtime.holodeck_gap_bridge is MagicMock()  # not set

    def test_enabled_wires_bridge(self):
        from probos.startup.finalize import _wire_holodeck_scenarios
        runtime = MagicMock(spec=["emit_event", "qualification_harness",
                                   "discovery_scenario_registry"])
        runtime.emit_event = lambda *a, **k: None
        runtime.qualification_harness = MagicMock(spec=QualificationHarness)
        runtime.discovery_scenario_registry = DiscoveryScenarioRegistry()
        config = MagicMock()
        config.holodeck_scenarios = HolodeckScenarioConfig(enabled=True)
        assert _wire_holodeck_scenarios(runtime=runtime, config=config) is True
        assert isinstance(runtime.holodeck_gap_bridge, HolodeckGapBridge)
        assert runtime.holodeck_gap_bridge.qualification_harness is runtime.qualification_harness

    def test_enabled_no_harness_still_wires(self):
        from probos.startup.finalize import _wire_holodeck_scenarios
        runtime = MagicMock(spec=["emit_event", "qualification_harness",
                                   "discovery_scenario_registry"])
        runtime.emit_event = None
        runtime.qualification_harness = None
        runtime.discovery_scenario_registry = None
        config = MagicMock()
        config.holodeck_scenarios = HolodeckScenarioConfig(enabled=True)
        assert _wire_holodeck_scenarios(runtime=runtime, config=config) is True
        assert isinstance(runtime.holodeck_gap_bridge, HolodeckGapBridge)
```

---

## Section 6 — Tracker updates

Apply in this order:

1. **`PROGRESS.md`** — append a new entry to the running ledger at line 1 (or wherever Wave 99's `AD-486 v1 CLOSED` entry sits). Format: `AD-539b v1 CLOSED. Holodeck Scenario Generation from Skill Gaps (GH issue #12, Wave 100). New module src/probos/holodeck/scenarios.py with GapScenarioGenerator + HolodeckGapDrill (QualificationTest Protocol impl) + HolodeckScenarioStore (SQLite via ConnectionFactory + in-memory fallback) + HolodeckGapBridge orchestrator. Reuses AD-512 DiscoveryScenarioRegistry for category matching (8 default scenarios across analysis/communication/coordination/construction/diagnosis); falls back to templated DiscoveryScenario keyed on gap.priority. Bridge auto-registers HolodeckGapDrill with AD-477 QualificationHarness so AD-628d DrillCalendar can schedule and execute it (unblocks AD-628d-1 forcing function). 4 new EventTypes. New HolodeckScenarioConfig (enabled=False per AD-695). New _wire_holodeck_scenarios finalize wirer + runtime.holodeck_gap_bridge public attribute. Optional holodeck_bridge=None kwarg on AD-539 trigger_qualification_if_needed (default None preserves byte-for-byte behavior). Idempotent against gap.id; back-fills gap.qualification_path_id. Deferred: AD-539b-d (ZPDCalibrator-driven difficulty calibration — forcing function: ≥10 outcomes per agent under enabled=True), AD-539b-e (auto-schedule via AD-628d DrillCalendar — forcing function: AD-628d-1 drafted). ~38 focused tests pass at tests/test_ad539b_holodeck_scenarios.py. Closes GH issue #12.`

2. **`docs/development/roadmap.md`** — at line 1260, replace `AD-539b (Holodeck scenario generation from gaps)` deferral note with a one-line completion note: `AD-539b (Holodeck scenario generation from gaps — **shipped Wave 100**, unblocks AD-628d-1)`. Also update the Lab Tech crew role line at `:2921` to add a note: `Laboratory Technician — wait for AD-539b (Holodeck) — unblocked Wave 100; awaiting role-spec AD`.

3. **`decisions-era-4-evolution.md`** — at line 2098, append after the existing `Status:` line: `Status (2026-05-07): AD-539b shipped (Wave 100). AD-539c, AD-539d remain deferred.`

4. **`prompts/wave-plan.yaml`** — append a new entry mirroring the W99 shape:

```yaml
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
```

---

## Section 7 — Canonical commit message + close paragraph

**Builder commit message** (single AD commit):

```
AD-539b: Holodeck scenario generation from skill gaps (generator+drill+bridge+store+wirer+gap-predictor-hook) (+~38 tests)
```

**Wave archive commit** (separate from the build commit):

```
Wave 100 archive: AD-539b holodeck scenario generation from skill gaps (#12)
```

**GH issue #12 close paragraph:**

> Closed by Wave 100 (AD-539b Holodeck scenario generation from skill gaps, +~38 tests). New `src/probos/holodeck/scenarios.py` with `GapScenarioGenerator` (matches `gap.affected_intent_types` + `gap.mapped_skill_id` against AD-512 `DiscoveryScenarioRegistry`'s 8 default scenarios via `_INTENT_CATEGORY_HINTS` table; falls back to templated `DiscoveryScenario` keyed on priority), `HolodeckGapDrill` (implements AD-477 `QualificationTest` Protocol verbatim; auto-registers with `QualificationHarness` so AD-628d `DrillCalendar` can schedule it), `HolodeckScenarioStore` (SQLite via `probos.storage.sqlite_factory.default_factory` ConnectionFactory + in-memory fallback), and `HolodeckGapBridge` orchestrator (idempotent, back-fills `gap.qualification_path_id`). 4 new `EventType` values appended to AD-486 cluster. New `HolodeckScenarioConfig(enabled=False)` per AD-695. New `_wire_holodeck_scenarios` finalize wirer + `runtime.holodeck_gap_bridge` public attribute. Optional `holodeck_bridge=None` kwarg on AD-539 `trigger_qualification_if_needed` preserves byte-for-byte default behavior. **Unblocks AD-628d-1** (TRAINO Holodeck-driven drill scheduling — W93 forcing function "AD-486 + AD-539b ship the Holodeck primitive" now satisfied). Deferred with explicit forcing functions: AD-539b-d (ZPDCalibrator-driven difficulty calibration — wait for ≥10 outcomes per agent under enabled=True), AD-539b-e (auto-schedule via AD-628d DrillCalendar — wait for AD-628d-1 draft).

---

## What this AD does NOT change (out-of-scope)

- **No mutation of AD-486 BirthChamber.** Birth-chamber graduation gates (`gates.py`) are untouched. AD-539b lives parallel to AD-486 — they integrate via the AD-477 `QualificationHarness` they both can register against.
- **No mutation of AD-477 QualificationHarness.** `register_test`, `run_test`, `registered_tests` API is consumed verbatim — Section 0 introduces zero new methods on the harness.
- **No mutation of AD-512 DiscoveryScenarioRegistry.** The registry is consumed through its existing public API (`list_by_category`, `get_scenario`). Section 0 introduces zero new methods on the registry.
- **No mutation of AD-539 GapReport dataclass shape.** Only `gap.qualification_path_id` is back-filled (already an existing field at `gap_predictor.py:201`).
- **No new pool, no new agent, no new standing-order content.** This is a substrate AD; consumer AD (TRAINO, Lab Tech, AD-510) lands later.
- **No HXI surface.** Operator visibility into generated scenarios is deferred to a future HXI panel AD; v1 ships event emission only.
- **No NATS coupling.** Bridge is in-process; cross-instance scenario distribution is wrong-repo by design.
- **No destructive intent.** The bridge is observation-and-registration only — `requires_consensus` not applicable.
- **No commercial-tagged feature in this prompt.** Cross-instance scenario-library distribution, customer-defined templates, and outcome-style consulting on scenario libraries are class-extension territory under the private commercial-repo path token surface; this AD ships the OSS substrate only.

---

## Acceptance criteria

1. Pre-flight checklist (Wave 100 dispatch §"Pre-flight checklist") all pass before any source edit.
2. All 6 implementation sections applied without phantom-API resolution failures.
3. `tests/test_ad539b_holodeck_scenarios.py` collects ~38 tests; all pass under `pytest -n 0`.
4. Full gate `pytest tests/ -q -n 4 --dist=loadfile` returns ≥12305 passed (+34 floor over baseline 12271; aim +38).
5. Phantom-API pre-check on the prompt body: 0 NEW genuine phantoms; documented FP count in build report.
6. Pre-commit-hook simulation `Select-String` against the 11 banned-pattern descriptors returns zero literal hits across both prompt files.
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`** (SOLID, three-tier exception handling, type annotations on public APIs, no mutable Pydantic defaults, frozen-dataclass field ordering, no fire-and-forget tasks, layer discipline preserved).
8. GH issue #12 closed with the canonical paragraph in §7.
9. Wave-plan W100 entry appended.
10. Tracker updates (PROGRESS.md / roadmap.md / era-4) all applied.

---

## Verified Against Codebase (2026-05-07)

```
git rev-parse HEAD
  6d34fcb (HEAD -> main, origin/main, origin/HEAD) Wave 99 archive: AD-486 holodeck birth chamber (#24)

# AD-486 v1 substrate (Wave 99 ship)
Select-String -Path src\probos\holodeck\__init__.py -Pattern "BirthChamber|HolodeckPhase|DepartmentActivationScheduler"
  src/probos/holodeck/__init__.py:13: from probos.holodeck.affect import (...)
  src/probos/holodeck/__init__.py:18: from probos.holodeck.chamber import BirthChamber, BirthChamberRecord
  src/probos/holodeck/__init__.py:19: from probos.holodeck.phases import HolodeckPhase
  src/probos/holodeck/__init__.py:20: from probos.holodeck.scheduler import DepartmentActivationScheduler

# AD-477 v1 surface
Select-String -Path src\probos\cognitive\qualification.py -Pattern "class QualificationTest|class TestResult|class QualificationHarness|class QualificationStore|def register_test|registered_tests|async def run_test"
  src/probos/cognitive/qualification.py:39:  class QualificationTest(Protocol):
  src/probos/cognitive/qualification.py:74:  class TestResult:
  src/probos/cognitive/qualification.py:136: class QualificationStore:
  src/probos/cognitive/qualification.py:350: class QualificationHarness:
  src/probos/cognitive/qualification.py:371: def register_test(self, test: QualificationTest) -> None:
  src/probos/cognitive/qualification.py:375: @property def registered_tests(self) -> dict[str, QualificationTest]:
  src/probos/cognitive/qualification.py:380: async def run_test(self, agent_id, test_name, runtime) -> TestResult:

# AD-512 v1 surface (DiscoveryScenarioRegistry catalog)
Select-String -Path src\probos\crew_development\discovery\scenarios.py -Pattern "class DiscoveryScenario|class DiscoveryScenarioRegistry|def list_by_category|def list_by_difficulty_band|def get_scenario|_DEFAULT_SCENARIOS"
  src/probos/crew_development/discovery/scenarios.py:23:  class DiscoveryScenario:
  src/probos/crew_development/discovery/scenarios.py:43:  _DEFAULT_SCENARIOS: tuple[DiscoveryScenario, ...] = (
  src/probos/crew_development/discovery/scenarios.py:144: class DiscoveryScenarioRegistry:
  src/probos/crew_development/discovery/scenarios.py:168: def get_scenario(self, scenario_id: str) -> DiscoveryScenario | None:
  src/probos/crew_development/discovery/scenarios.py:174: def list_by_category(self, category: str) -> tuple[DiscoveryScenario, ...]:
  src/probos/crew_development/discovery/scenarios.py:181: def list_by_difficulty_band(...)

# AD-539 v1 surface (GapReport + pipeline)
Select-String -Path src\probos\cognitive\gap_predictor.py -Pattern "class GapReport|^def classify_gap|^def detect_gaps|^async def map_gap_to_skill|^async def trigger_qualification_if_needed"
  src/probos/cognitive/gap_predictor.py:186: class GapReport:
  src/probos/cognitive/gap_predictor.py:229: def classify_gap(...)
  src/probos/cognitive/gap_predictor.py:258: def detect_gaps(...)
  src/probos/cognitive/gap_predictor.py:420: async def map_gap_to_skill(...)
  src/probos/cognitive/gap_predictor.py:474: async def trigger_qualification_if_needed(...)

# Existing EventTypes block ending point
Select-String -Path src\probos\events.py -Pattern "HOLODECK_AGENT_ADMITTED|HOLODECK_AFFECTIVE_BASELINE_OBSERVED|DISCOVERY_SCENARIO_OFFERED"
  src/probos/events.py:388: HOLODECK_AGENT_ADMITTED = "holodeck_agent_admitted"
  src/probos/events.py:393: HOLODECK_AFFECTIVE_BASELINE_OBSERVED = "holodeck_affective_baseline_observed"
  src/probos/events.py:396: DISCOVERY_SCENARIO_OFFERED = "discovery_scenario_offered"  # AD-512a registry

# No collision for new EventType values
Select-String -Path src\probos\events.py -Pattern "HOLODECK_SCENARIO_"
  (no output — collision-free)

# Config anchor
Select-String -Path src\probos\config.py -Pattern "class HolodeckBirthChamberConfig|holodeck_birth_chamber:"
  src/probos/config.py:1756: class HolodeckBirthChamberConfig(BaseModel):
  src/probos/config.py:2796: holodeck_birth_chamber: HolodeckBirthChamberConfig = HolodeckBirthChamberConfig()

# Finalize wirer anchor
Select-String -Path src\probos\startup\finalize.py -Pattern "_wire_birth_chamber|_wire_discovery_learning"
  src/probos/startup/finalize.py:159:  def _wire_birth_chamber(*, runtime: Any, config: "SystemConfig") -> bool:
  src/probos/startup/finalize.py:241:  def _wire_discovery_learning(*, runtime: Any, config: "SystemConfig") -> bool:
  src/probos/startup/finalize.py:1543: if _wire_birth_chamber(runtime=runtime, config=config):

# Public runtime attrs already at HEAD (consumed by wirer late-bind)
Select-String -Path src\probos\startup\finalize.py -Pattern "runtime\.discovery_scenario_registry|runtime\.zpd_calibrator"
  src/probos/startup/finalize.py:261:  runtime.discovery_scenario_registry = scenario_registry
  src/probos/startup/finalize.py:274:  runtime.zpd_calibrator = zpd_calibrator

# AD-628d DrillCalendar consumption pattern (downstream consumer; not modified by W100)
Select-String -Path src\probos\cognitive\drill_calendar.py -Pattern "class DrillCalendar|self._harness\.run_test|registered_tests"
  src/probos/cognitive/drill_calendar.py:30:  class DrillCalendar:
  src/probos/cognitive/drill_calendar.py:46:  return set(self._harness.registered_tests.keys())
  src/probos/cognitive/drill_calendar.py:99:  result = await self._harness.run_test(entry.agent_id, entry.qualification_test, self._runtime,)

# AD-628d-1 forcing function reference (pointing here)
Select-String -Path prompts\archive\WAVE-93-DISPATCH.md -Pattern "AD-628d-1.*Holodeck Scenario|AD-486 \+ AD-539b"
  prompts/archive/WAVE-93-DISPATCH.md:55: AD-628d-1 (Holodeck Scenario Selection — TRAINO-driven holodeck-scenario lifecycle ...
  prompts/archive/WAVE-93-DISPATCH.md:55: ... forcing function: AD-486 + AD-539b ship the Holodeck primitive)

# ConnectionFactory import path (verified via AD-477 precedent)
Select-String -Path src\probos\cognitive\qualification.py -Pattern "from probos.storage.sqlite_factory|default_factory"
  src/probos/cognitive/qualification.py:175: from probos.storage.sqlite_factory import default_factory

# AD-695 transitional-flag precedent + AD-486 default-False precedent
Select-String -Path src\probos\config.py -Pattern "enabled: bool = False" | Select-Object -First 5
  (multiple — confirms default-False is the AD-695 standard for transitional flags)

# Greenfield checks
git ls-files src/probos/holodeck/scenarios.py
  (no output — file does not exist; greenfield)
git ls-files tests/test_ad539b_holodeck_scenarios.py
  (no output — file does not exist; greenfield)
```

All 16 grep anchors confirm extension-point existence at HEAD `6d34fcb`. The four-pass review record is documented in the dispatch file's `## Architect review-pass record` section.
