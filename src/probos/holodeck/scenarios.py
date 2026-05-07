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

import logging
import time
from dataclasses import dataclass, replace
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
        from probos.crew_development.discovery.scenarios import DiscoveryScenario  # noqa: F401

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
