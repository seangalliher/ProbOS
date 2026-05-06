# AD-512 v1 — Discovery-Based Capability Building (Substrate)

**Closes:** GH issue #94
**HEAD:** `7504430` (post-Wave-83)
**Baseline:** 11673 → target ≥ 11703 (Δ ≥ +30; 32 tests planned)
**OSS only.** No HXI surface. No router. No new Intent. No LLM call inside any v1 module. No commercial content.
**Sub-AD letters in scope (concrete substrate):** AD-512a (DiscoveryScenario registry), AD-512b (StrengthMap), AD-512c (CrossFunctionalSuggestion helper), AD-512d (GrowthMindsetFramer pure helpers), AD-512e (CapabilityConfidenceScorer Beta(α,β) per capability), AD-512f (ZPDCalibrator).
**Sub-AD letters hard-deferred:** none. Captain rule honored — every sub-AD ships as substrate now; future AD-486 Holodeck wave consumes this substrate without modifying it.

## Problem

Roadmap line 6407 (`docs/development/roadmap.md`) plans AD-512 as discovery-based capability building: agents discover their strengths and limits through Holodeck experience rather than being told "you can't do X." The roadmap names six capabilities — discovery scenarios, strength mapping, cross-functional awareness, growth mindset framing, capability confidence scoring, Vygotsky ZPD calibration. None exists at HEAD.

Verify-first against `7504430` confirms the substrate gap:

- `src/probos/crew_development/` package exists (`curriculum.py` AD-507 v1, `boot_camp.py` AD-509 v1) but contains NO discovery, strength, confidence, or ZPD module. (`Test-Path` returns False on every candidate path.)
- `src/probos/crew_development/__init__.py` exports `CoreKnowledgeCurriculumRegistry` only.
- `EventType` registry at `events.py:354` has `CURRICULUM_MODULE_QUERIED` (AD-507) and `events.py:357` `BOOT_CAMP_PHASE_ADVANCED` (AD-509) — adjacent insertion site for AD-512 events.
- `SystemConfig` at `config.py:2607-2611` has `crew_development: CrewDevelopmentConfig` (AD-507) and `boot_camp_phase: BootCampPhaseConfig` (AD-509). No `discovery_learning` field.
- `_wire_curriculum_registry` (`finalize.py:122`) and `_wire_boot_camp_tracker` (`finalize.py:141`) are the AD-507/509 v1 wirer pattern. `finalize.py:1308-1312` invokes them in sequence. No AD-512 wirer.
- `HebbianRouter.record_interaction(source, target, success, rel_type)` at `routing.py:177` is the natural consumer for cross-functional Hebbian seeding — but v1 only *suggests* (returns the (source, target, success, rel_type) tuple); it does NOT call `record_interaction`. The discovery substrate ships observational and the (eventual) AD-486 Holodeck wave wires the actual Hebbian write.
- `Episode` dataclass at `types.py:439` has `importance: int = 5` field — the natural target for discovery-episode encoding. v1 does NOT call `EpisodicMemory.store()`; provides a `to_episode_payload()` helper instead.
- `PersonalOntologyProber` (AD-487) at `cognitive/self_distillation/prober.py:66` already exists; AD-512 v1 emits `STRENGTH_MAP_UPDATED` events the prober *can* later subscribe to but explicitly does NOT subscribe today.
- `AD-486` Holodeck Birth Chamber, the natural primary consumer, is NOT yet shipped. Same situation as AD-507/509/511 v1: observational substrate now, consumer wave later.

GH #94 calls for the AD-512 substrate. Six capabilities ship concretely as observational primitives following the AD-507/509/511 v1 pattern. Captain rule "don't defer unless no choice" is honored — zero hard-deferrals. Each capability has a clear data shape, a public attribute on `runtime`, and tests that exercise it without requiring the (absent) Holodeck consumer.

## Solution

One new sub-package + 5 EventTypes + 1 Pydantic config + 1 finalize wirer + 4 public runtime attributes + 32 tests.

1. **`src/probos/crew_development/discovery/`** — new sub-package with six modules:
   - `scenarios.py` — `DiscoveryScenario` frozen dataclass + `DiscoveryScenarioRegistry` (read-only catalog of 8 default scenarios spanning 5 capability categories).
   - `strength_map.py` — `StrengthRecord` frozen dataclass + `StrengthMap` (per-agent record of scenario outcomes; `record_outcome` / `get_strengths` / `get_struggles` / `to_episode_payload`).
   - `cross_functional.py` — `CrossFunctionalSuggestion` frozen dataclass + `suggest_routing(...)` pure function returning `(source, target, success, rel_type)` tuple shape. Caller (eventual AD-486 wave) decides whether to call `runtime.hebbian_router.record_interaction(...)`.
   - `framing.py` — pure helpers `frame_as_growth(limitation_text)` and `frame_as_discovery(struggle_text)`. No state. Replaces "you can't do X" → "you have not yet developed X" patterns.
   - `confidence.py` — `CapabilityConfidence` frozen dataclass with raw Beta(α,β) parameters + `CapabilityConfidenceScorer` (per-agent per-capability Beta accumulator; `record_attempt(success)` increments α/β; `get_confidence(agent_id, capability)` returns mean = α/(α+β); `get_calibration(agent_id, capability)` returns Beta variance for "how confident is the confidence").
   - `zpd.py` — `ZPDBand` frozen dataclass (lower/upper difficulty bounds + scaffolding level) + `ZPDCalibrator` (selects scenarios within an agent's Zone of Proximal Development given current confidence; `select_scenarios(agent_id, capability, scenarios) -> tuple[DiscoveryScenario, ...]`).

2. **`src/probos/crew_development/discovery/__init__.py`** — re-exports the public surface.

3. **`src/probos/events.py`** — +5 EventType values inserted immediately after the AD-509 `BOOT_CAMP_PHASE_ADVANCED` block (line 357).

4. **`src/probos/config.py`** — `DiscoveryLearningConfig` Pydantic model (default-True, observational only — same precedent as AD-507/509/511 v1) + `SystemConfig.discovery_learning` field adjacent to `boot_camp_phase`.

5. **`src/probos/startup/finalize.py`** — new `_wire_discovery_learning(*, runtime, config) -> bool` placed immediately after `_wire_boot_camp_tracker`. Invocation in the dispatch block at `finalize.py:1311` adjacent to AD-509.

6. **`src/probos/runtime.py`** — none required (4 new public attributes are set by the wirer; no `__init__` declarations for AD-507/509/511 v1 either; this AD follows that precedent).

7. **`tests/test_ad512_discovery_learning.py`** — 32 tests across 8 classes.

---

## Section 0 — EventTypes

### File: `src/probos/events.py`

Insert AD-512 events immediately after the AD-509 `BOOT_CAMP_PHASE_ADVANCED` block (line 357). Adjacent placement keeps Crew Development events together.

```text
===MODIFY: src/probos/events.py===
===SEARCH===
    # ── Boot Camp Phase Tracker (AD-509) ───────────────────────────
    BOOT_CAMP_PHASE_ADVANCED = "boot_camp_phase_advanced"  # AD-509

    # ── Statistical Process Control (AD-522) ───────────────────────
===REPLACE===
    # ── Boot Camp Phase Tracker (AD-509) ───────────────────────────
    BOOT_CAMP_PHASE_ADVANCED = "boot_camp_phase_advanced"  # AD-509

    # ── Discovery-Based Capability Building (AD-512) ───────────────
    DISCOVERY_SCENARIO_OFFERED = "discovery_scenario_offered"  # AD-512a registry
    DISCOVERY_OUTCOME_RECORDED = "discovery_outcome_recorded"  # AD-512b StrengthMap
    STRENGTH_MAP_UPDATED = "strength_map_updated"  # AD-512b StrengthMap
    CAPABILITY_CONFIDENCE_UPDATED = "capability_confidence_updated"  # AD-512e
    ZPD_SCENARIO_CALIBRATED = "zpd_scenario_calibrated"  # AD-512f

    # ── Statistical Process Control (AD-522) ───────────────────────
===END REPLACE===
```

Verification: `grep -nE "DISCOVERY_SCENARIO_OFFERED|DISCOVERY_OUTCOME_RECORDED|STRENGTH_MAP_UPDATED|CAPABILITY_CONFIDENCE_UPDATED|ZPD_SCENARIO_CALIBRATED" src/probos/events.py` returns exactly 5 hits, all on enum lines.

---

## Section 1 — Pydantic config

### File: `src/probos/config.py`

Insert `DiscoveryLearningConfig` immediately after `BootCampPhaseConfig` (line ~2419-2429). Add `SystemConfig.discovery_learning` field adjacent to `SystemConfig.boot_camp_phase` at line 2608.

```text
===MODIFY: src/probos/config.py===
===SEARCH===
class BootCampPhaseConfig(BaseModel):
    """AD-509 v1: Boot Camp Phase Tracker (in-memory observational).

    Disambiguated from AD-638 ``BootCampConfig`` (cold-start boot camp); the
    AD-509 v1 tracker records 5-phase progression per agent.
    """

    enabled: bool = True
    # v1: tracker only. A-School curriculum, graduated stimuli,
    # completion-criteria gating, and trait-adaptive pacing are deferred
    # to AD-509b/c/d/e.


class ScopedCognitionConfig(BaseModel):
===REPLACE===
class BootCampPhaseConfig(BaseModel):
    """AD-509 v1: Boot Camp Phase Tracker (in-memory observational).

    Disambiguated from AD-638 ``BootCampConfig`` (cold-start boot camp); the
    AD-509 v1 tracker records 5-phase progression per agent.
    """

    enabled: bool = True
    # v1: tracker only. A-School curriculum, graduated stimuli,
    # completion-criteria gating, and trait-adaptive pacing are deferred
    # to AD-509b/c/d/e.


class DiscoveryLearningConfig(BaseModel):
    """AD-512 v1: Discovery-Based Capability Building substrate (observational).

    Default-True follows AD-507/509/511 v1 precedent — substrate is in-memory
    only, emits events, no resource creation, no I/O, no LLM calls. The
    eventual AD-486 Holodeck wave is the consumer that drives outcomes
    through this substrate; v1 ships the registry + per-agent maps + ZPD
    calibrator without that consumer.
    """

    enabled: bool = True
    # v1: 8 default scenarios + Beta(1,1) confidence priors + scaffolding
    # heuristic. Hebbian writes, episode storage, and Holodeck wiring are
    # caller responsibilities and are deferred to AD-486 / AD-510.
    confidence_prior_alpha: float = Field(default=1.0, ge=0.01)
    confidence_prior_beta: float = Field(default=1.0, ge=0.01)
    zpd_lower_bound: float = Field(default=0.40, ge=0.0, le=1.0)
    zpd_upper_bound: float = Field(default=0.75, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_zpd_band(self) -> "DiscoveryLearningConfig":
        if self.zpd_lower_bound >= self.zpd_upper_bound:
            raise ValueError(
                "zpd_lower_bound must be strictly less than zpd_upper_bound"
            )
        return self


class ScopedCognitionConfig(BaseModel):
===END REPLACE===
```

Add `SystemConfig` field immediately after `boot_camp_phase`:

```text
===MODIFY: src/probos/config.py===
===SEARCH===
    boot_camp_phase: BootCampPhaseConfig = Field(default_factory=BootCampPhaseConfig)  # AD-509
    scoped_cognition: ScopedCognitionConfig = Field(default_factory=ScopedCognitionConfig)  # AD-508
===REPLACE===
    boot_camp_phase: BootCampPhaseConfig = Field(default_factory=BootCampPhaseConfig)  # AD-509
    discovery_learning: DiscoveryLearningConfig = Field(default_factory=DiscoveryLearningConfig)  # AD-512
    scoped_cognition: ScopedCognitionConfig = Field(default_factory=ScopedCognitionConfig)  # AD-508
===END REPLACE===
```

`model_validator` and `field_validator` are already imported at `config.py:10` (`from pydantic import BaseModel, Field, field_validator, model_validator`).

---

## Section 2 — DiscoveryScenario registry (AD-512a)

### File: `src/probos/crew_development/discovery/__init__.py`

```text
===FILE: src/probos/crew_development/discovery/__init__.py===
"""AD-512 v1: Discovery-Based Capability Building substrate.

Six capability primitives that future Holodeck consumers (AD-486 Birth
Chamber, AD-510 Team Simulations) wire together to drive experiential
learning — discovery scenarios, strength mapping, cross-functional
suggestion, growth mindset framing, capability confidence (Beta(α,β)),
and Vygotsky ZPD calibration. v1 is observational only.

No consumers in v1 — content delivery and Hebbian/episodic writes are
caller responsibilities. AD-486 / AD-510 will consume this substrate.
"""

from probos.crew_development.discovery.scenarios import (
    DiscoveryScenario,
    DiscoveryScenarioRegistry,
)
from probos.crew_development.discovery.strength_map import (
    StrengthMap,
    StrengthRecord,
)
from probos.crew_development.discovery.cross_functional import (
    CrossFunctionalSuggestion,
    suggest_routing,
)
from probos.crew_development.discovery.framing import (
    frame_as_discovery,
    frame_as_growth,
)
from probos.crew_development.discovery.confidence import (
    CapabilityConfidence,
    CapabilityConfidenceScorer,
)
from probos.crew_development.discovery.zpd import (
    ZPDBand,
    ZPDCalibrator,
)

__all__ = [
    "DiscoveryScenario",
    "DiscoveryScenarioRegistry",
    "StrengthMap",
    "StrengthRecord",
    "CrossFunctionalSuggestion",
    "suggest_routing",
    "frame_as_discovery",
    "frame_as_growth",
    "CapabilityConfidence",
    "CapabilityConfidenceScorer",
    "ZPDBand",
    "ZPDCalibrator",
]
===END FILE===
```

### File: `src/probos/crew_development/discovery/scenarios.py`

```text
===FILE: src/probos/crew_development/discovery/scenarios.py===
"""DiscoveryScenarioRegistry (AD-512a v1).

Read-only catalog of capability discovery scenarios. Future Holodeck
consumers (AD-486, AD-510) read this registry, present scenarios, and
record outcomes via :class:`StrengthMap`.

v1 ships registry only; the registry never writes Hebbian edges or
episodes — those are caller responsibilities reserved for AD-486 / AD-510.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveryScenario:
    """A discovery scenario the Holodeck (AD-486) can present.

    ``capability_category`` is one of: ``analysis``, ``communication``,
    ``coordination``, ``construction``, ``diagnosis``.

    ``difficulty`` is a normalized scalar on [0.0, 1.0] used by the ZPD
    calibrator. ``scaffolding_level`` is one of ``high``, ``medium``,
    ``low``, ``none`` — a hint for the eventual presenter.
    """

    scenario_id: str
    title: str
    capability_category: str
    summary: str
    learning_objectives: tuple[str, ...]
    difficulty: float
    scaffolding_level: str


_DEFAULT_SCENARIOS: tuple[DiscoveryScenario, ...] = (
    DiscoveryScenario(
        scenario_id="diagnose_simple_fault",
        title="Diagnose a single-component fault",
        capability_category="diagnosis",
        summary="One subsystem reports anomaly; isolate cause and propose remediation.",
        learning_objectives=(
            "Identify the failing component",
            "Distinguish symptom from root cause",
            "Propose a reversible remediation",
        ),
        difficulty=0.30,
        scaffolding_level="high",
    ),
    DiscoveryScenario(
        scenario_id="diagnose_cross_subsystem",
        title="Diagnose a fault spanning two subsystems",
        capability_category="diagnosis",
        summary="Symptoms appear in two subsystems; locate the upstream cause.",
        learning_objectives=(
            "Trace causality across subsystem boundaries",
            "Recognize when a peer expert is needed",
        ),
        difficulty=0.65,
        scaffolding_level="medium",
    ),
    DiscoveryScenario(
        scenario_id="analyze_telemetry_window",
        title="Analyze a telemetry window for anomalies",
        capability_category="analysis",
        summary="Given a 5-minute telemetry window, identify outlier signals.",
        learning_objectives=(
            "Apply baseline-vs-window comparison",
            "Distinguish noise from signal",
        ),
        difficulty=0.45,
        scaffolding_level="medium",
    ),
    DiscoveryScenario(
        scenario_id="compose_briefing",
        title="Compose a briefing for the Captain",
        capability_category="communication",
        summary="Summarize a multi-thread Ward Room exchange in 4 sentences.",
        learning_objectives=(
            "Identify the Captain's decision question",
            "Suppress side detail; surface the actionable signal",
        ),
        difficulty=0.40,
        scaffolding_level="medium",
    ),
    DiscoveryScenario(
        scenario_id="coordinate_two_dept_handoff",
        title="Coordinate a two-department handoff",
        capability_category="coordination",
        summary="Engineering and Medical share an artifact; route the handoff cleanly.",
        learning_objectives=(
            "Identify each department's authoritative role",
            "Recognize when to escalate vs proceed",
        ),
        difficulty=0.55,
        scaffolding_level="medium",
    ),
    DiscoveryScenario(
        scenario_id="construct_remediation_plan",
        title="Construct a remediation plan from a diagnosis",
        capability_category="construction",
        summary="Given a confirmed diagnosis, produce a 3-step reversible remediation.",
        learning_objectives=(
            "Order steps so each is reversible at its boundary",
            "Identify the gate for crew approval",
        ),
        difficulty=0.60,
        scaffolding_level="low",
    ),
    DiscoveryScenario(
        scenario_id="construct_research_proposal",
        title="Construct a research proposal",
        capability_category="construction",
        summary="From an open question, produce a researchable proposal.",
        learning_objectives=(
            "Frame the question as falsifiable",
            "Identify scope boundaries",
        ),
        difficulty=0.75,
        scaffolding_level="low",
    ),
    DiscoveryScenario(
        scenario_id="communicate_under_time_pressure",
        title="Communicate a decision under time pressure",
        capability_category="communication",
        summary="60-second window to brief the Captain on a fast-moving incident.",
        learning_objectives=(
            "Surface the single most decision-relevant fact",
            "Suppress reflexive caveat-stacking",
        ),
        difficulty=0.70,
        scaffolding_level="none",
    ),
)


class DiscoveryScenarioRegistry:
    """Read-only registry of discovery scenarios. AD-512a v1.

    Default catalog seeds 8 scenarios across 5 capability categories.
    Extensible at runtime via :meth:`register_scenario` (no persistence
    in v1 — runtime-only).

    Public API:
        list_scenarios() -> tuple[DiscoveryScenario, ...]
        get_scenario(scenario_id) -> DiscoveryScenario | None
        list_by_category(category) -> tuple[DiscoveryScenario, ...]
        list_by_difficulty_band(low, high) -> tuple[DiscoveryScenario, ...]
        register_scenario(scenario) -> None
    """

    def __init__(self) -> None:
        self._scenarios: dict[str, DiscoveryScenario] = {
            s.scenario_id: s for s in _DEFAULT_SCENARIOS
        }
        self.emit_event: Callable[..., None] | None = None

    def list_scenarios(self) -> tuple[DiscoveryScenario, ...]:
        return tuple(self._scenarios.values())

    def get_scenario(self, scenario_id: str) -> DiscoveryScenario | None:
        s = self._scenarios.get(scenario_id)
        if s is not None:
            self._emit(scenario_id, "by_id")
        return s

    def list_by_category(self, category: str) -> tuple[DiscoveryScenario, ...]:
        out = tuple(s for s in self._scenarios.values() if s.capability_category == category)
        if out:
            self._emit("", f"by_category:{category}")
        return out

    def list_by_difficulty_band(
        self, low: float, high: float
    ) -> tuple[DiscoveryScenario, ...]:
        if low > high:
            return ()
        return tuple(
            s for s in self._scenarios.values()
            if low <= s.difficulty <= high
        )

    def register_scenario(self, scenario: DiscoveryScenario) -> None:
        """Add or overwrite a scenario by id (runtime-only; not persisted)."""
        self._scenarios[scenario.scenario_id] = scenario

    def _emit(self, scenario_id: str, query_type: str) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.DISCOVERY_SCENARIO_OFFERED,
                {
                    "scenario_id": scenario_id,
                    "query_type": query_type,
                },
            )
        except Exception:
            logger.warning(
                "AD-512a: emit_event failed for scenario_id=%s; continuing without event",
                scenario_id,
                exc_info=True,
            )
===END FILE===
```

---

## Section 3 — StrengthMap (AD-512b)

### File: `src/probos/crew_development/discovery/strength_map.py`

```text
===FILE: src/probos/crew_development/discovery/strength_map.py===
"""StrengthMap — per-agent record of discovery-scenario outcomes (AD-512b v1).

Future consumers (AD-486 Holodeck post-scenario hook, AD-487 Personal
Ontology Prober) read this map to enrich self-knowledge. v1 is
observational — :meth:`record_outcome` updates the map and emits an
event; the caller separately decides whether to write a Hebbian edge
(see :func:`cross_functional.suggest_routing`) or store an episode (see
:meth:`to_episode_payload`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrengthRecord:
    """One scenario outcome recorded against an agent. AD-512b v1."""

    agent_id: str
    scenario_id: str
    capability_category: str
    success: bool
    confidence_self_report: float  # 0.0–1.0; agent's own confidence at attempt
    timestamp: float
    notes: str = ""


@dataclass
class _AgentStrengthAggregate:
    """Per-agent rolling aggregate. Internal."""

    agent_id: str
    successes_by_category: dict[str, int] = field(default_factory=dict)
    failures_by_category: dict[str, int] = field(default_factory=dict)
    last_outcome_at: float = 0.0

    def total_attempts(self, category: str) -> int:
        return (
            self.successes_by_category.get(category, 0)
            + self.failures_by_category.get(category, 0)
        )

    def success_rate(self, category: str) -> float:
        n = self.total_attempts(category)
        if n == 0:
            return 0.0
        return self.successes_by_category.get(category, 0) / n


class StrengthMap:
    """In-memory per-agent strength map. AD-512b v1.

    Public API:
        record_outcome(record) -> None
        records_for(agent_id) -> tuple[StrengthRecord, ...]
        get_strengths(agent_id, *, min_attempts=2, threshold=0.70) -> tuple[str, ...]
        get_struggles(agent_id, *, min_attempts=2, threshold=0.40) -> tuple[str, ...]
        success_rate(agent_id, category) -> float
        total_attempts(agent_id, category) -> int
        to_episode_payload(record) -> dict[str, Any]
    """

    def __init__(self) -> None:
        self._records: list[StrengthRecord] = []
        self._aggregates: dict[str, _AgentStrengthAggregate] = {}
        self.emit_event: Callable[..., None] | None = None

    def record_outcome(self, record: StrengthRecord) -> None:
        """Append a record and update the per-agent aggregate."""
        self._records.append(record)
        agg = self._aggregates.get(record.agent_id)
        if agg is None:
            agg = _AgentStrengthAggregate(agent_id=record.agent_id)
            self._aggregates[record.agent_id] = agg
        bucket = agg.successes_by_category if record.success else agg.failures_by_category
        bucket[record.capability_category] = bucket.get(record.capability_category, 0) + 1
        agg.last_outcome_at = record.timestamp
        self._emit_outcome(record)
        self._emit_map_updated(record.agent_id, record.capability_category)

    def records_for(self, agent_id: str) -> tuple[StrengthRecord, ...]:
        return tuple(r for r in self._records if r.agent_id == agent_id)

    def success_rate(self, agent_id: str, capability_category: str) -> float:
        agg = self._aggregates.get(agent_id)
        if agg is None:
            return 0.0
        return agg.success_rate(capability_category)

    def total_attempts(self, agent_id: str, capability_category: str) -> int:
        agg = self._aggregates.get(agent_id)
        if agg is None:
            return 0
        return agg.total_attempts(capability_category)

    def get_strengths(
        self,
        agent_id: str,
        *,
        min_attempts: int = 2,
        threshold: float = 0.70,
    ) -> tuple[str, ...]:
        """Return capability categories where success_rate >= threshold."""
        agg = self._aggregates.get(agent_id)
        if agg is None:
            return ()
        out: list[str] = []
        all_categories = set(agg.successes_by_category) | set(agg.failures_by_category)
        for cat in sorted(all_categories):
            if agg.total_attempts(cat) >= min_attempts and agg.success_rate(cat) >= threshold:
                out.append(cat)
        return tuple(out)

    def get_struggles(
        self,
        agent_id: str,
        *,
        min_attempts: int = 2,
        threshold: float = 0.40,
    ) -> tuple[str, ...]:
        """Return capability categories where success_rate < threshold."""
        agg = self._aggregates.get(agent_id)
        if agg is None:
            return ()
        out: list[str] = []
        all_categories = set(agg.successes_by_category) | set(agg.failures_by_category)
        for cat in sorted(all_categories):
            if agg.total_attempts(cat) >= min_attempts and agg.success_rate(cat) < threshold:
                out.append(cat)
        return tuple(out)

    @staticmethod
    def to_episode_payload(record: StrengthRecord) -> dict[str, Any]:
        """Build an Episode-shaped dict for caller-driven encoding.

        v1 does NOT call EpisodicMemory.store; the caller (AD-486 Holodeck
        wave) constructs an Episode from this dict and stores it.
        Discovery episodes are high-importance per AD-512 design (importance=8).
        """
        return {
            "user_input": f"discovery:{record.scenario_id}",
            "outcomes": [{
                "scenario_id": record.scenario_id,
                "capability_category": record.capability_category,
                "success": record.success,
                "self_confidence": record.confidence_self_report,
                "notes": record.notes,
            }],
            "agent_ids": [record.agent_id],
            "timestamp": record.timestamp,
            "importance": 8,
            "source": "discovery_learning",
        }

    def _emit_outcome(self, record: StrengthRecord) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.DISCOVERY_OUTCOME_RECORDED,
                {
                    "agent_id": record.agent_id,
                    "scenario_id": record.scenario_id,
                    "capability_category": record.capability_category,
                    "success": record.success,
                },
            )
        except Exception:
            logger.warning(
                "AD-512b: emit_event failed for outcome agent_id=%s; continuing",
                record.agent_id,
                exc_info=True,
            )

    def _emit_map_updated(self, agent_id: str, capability_category: str) -> None:
        if self.emit_event is None:
            return
        try:
            agg = self._aggregates[agent_id]
            self.emit_event(
                EventType.STRENGTH_MAP_UPDATED,
                {
                    "agent_id": agent_id,
                    "capability_category": capability_category,
                    "success_rate": agg.success_rate(capability_category),
                    "total_attempts": agg.total_attempts(capability_category),
                    "last_outcome_at": agg.last_outcome_at,
                },
            )
        except Exception:
            logger.warning(
                "AD-512b: map_updated emit failed for agent_id=%s; continuing",
                agent_id,
                exc_info=True,
            )
===END FILE===
```

`time` is not imported — v1 records receive `timestamp` from caller (StrengthRecord.timestamp is caller-supplied), keeping callers in control of the clock for testing. Sibling AD-509 `boot_camp.py` imports `time` because it uses `time.time()` as a default factory; AD-512 substrate has no analogous default-factory need.

---

## Section 4 — CrossFunctionalSuggestion helper (AD-512c)

### File: `src/probos/crew_development/discovery/cross_functional.py`

```text
===FILE: src/probos/crew_development/discovery/cross_functional.py===
"""Cross-functional Hebbian-routing suggestion (AD-512c v1).

Translates a discovery struggle into a *suggestion* of a Hebbian edge
that the eventual AD-486 Holodeck consumer can write via
``runtime.hebbian_router.record_interaction(...)``. v1 produces the
tuple shape only; **no Hebbian writes happen inside this module**.
"""

from __future__ import annotations

from dataclasses import dataclass

from probos.crew_development.discovery.strength_map import StrengthRecord


@dataclass(frozen=True)
class CrossFunctionalSuggestion:
    """A suggested Hebbian edge derived from a discovery outcome.

    Caller is responsible for invoking
    ``runtime.hebbian_router.record_interaction(source, target, success, rel_type)``
    (mesh.routing:177) when the design says the suggestion should be acted on.
    """

    source: str            # struggling agent_id
    target: str            # peer-expert agent_id whose strength matches
    success: bool          # True if suggesting to STRENGTHEN (peer succeeded
                           # where source struggled); False to weaken
    rel_type: str          # always "agent" — peer-relationship edge
    rationale: str         # short human-readable explanation


def suggest_routing(
    *,
    struggling_record: StrengthRecord,
    peer_expert_id: str,
) -> CrossFunctionalSuggestion:
    """Translate a struggle + a peer-expert id into a routing suggestion.

    Caller responsibilities (kept out of v1 to preserve substrate purity):
        1. Identify the peer expert (typically via
           ``StrengthMap.get_strengths(peer_id) ∩ struggling_record.capability_category``).
        2. Decide whether to write the edge by calling
           ``runtime.hebbian_router.record_interaction(...)``.
        3. Optionally emit a domain event after the write.

    The suggestion's ``success`` field is True when the source struggled
    (``not struggling_record.success``) — strengthening the edge to the
    peer-expert. If the source actually succeeded, ``success`` is False
    (no need to strengthen).
    """
    is_struggle = not struggling_record.success
    rationale = (
        f"{struggling_record.agent_id} struggled with "
        f"{struggling_record.capability_category} "
        f"(scenario {struggling_record.scenario_id}); "
        f"{peer_expert_id} is a peer expert."
    )
    return CrossFunctionalSuggestion(
        source=struggling_record.agent_id,
        target=peer_expert_id,
        success=is_struggle,
        rel_type="agent",
        rationale=rationale,
    )
===END FILE===
```

---

## Section 5 — GrowthMindsetFramer (AD-512d)

### File: `src/probos/crew_development/discovery/framing.py`

```text
===FILE: src/probos/crew_development/discovery/framing.py===
"""Growth-mindset framing helpers (AD-512d v1).

Pure functions. No state. No I/O. No event emission.

Replaces declarative-limit phrasing ("you can't do X") with
discovery / not-yet phrasing — Dweck growth-mindset framing per
AD-512 design principle #4.
"""

from __future__ import annotations


_GROWTH_PREFIXES: tuple[str, ...] = (
    "you can't ",
    "you cannot ",
    "you don't ",
    "you do not ",
    "you are unable to ",
    "you're unable to ",
)


def frame_as_growth(limitation_text: str) -> str:
    """Rewrite a declarative-limit string in growth-mindset terms.

    Replaces leading "you can't / you cannot / you don't / you are unable
    to" with "you have not yet developed " — keeping the rest of the
    string intact.

    Idempotent: applying twice returns the same string.

    Returns the original ``limitation_text`` unchanged when no recognized
    prefix is present.
    """
    if not limitation_text:
        return limitation_text
    lower = limitation_text.lstrip().lower()
    for prefix in _GROWTH_PREFIXES:
        if lower.startswith(prefix):
            # Preserve whitespace prefix if any.
            stripped = limitation_text.lstrip()
            leading_ws = limitation_text[: len(limitation_text) - len(stripped)]
            return f"{leading_ws}you have not yet developed {stripped[len(prefix):]}"
    return limitation_text


def frame_as_discovery(struggle_text: str) -> str:
    """Wrap a struggle description as a discovery prompt.

    Returns text shaped as "Through this experience you discovered: ..."
    Keeps the original ``struggle_text`` substring so episodic encoding
    keeps the original phrasing for retrieval.

    Returns the original ``struggle_text`` unchanged when empty.
    """
    if not struggle_text:
        return struggle_text
    return f"Through this experience you discovered: {struggle_text}"
===END FILE===
```

---

## Section 6 — CapabilityConfidenceScorer (AD-512e)

### File: `src/probos/crew_development/discovery/confidence.py`

```text
===FILE: src/probos/crew_development/discovery/confidence.py===
"""Capability confidence scorer (AD-512e v1).

Per-agent per-capability calibrated confidence using a Beta(α, β) update.
**Stores raw (alpha, beta) parameters per the ProbOS standing-order
trust principle** — never derived means.

The mean confidence is α / (α + β); the variance is the calibration
signal ("how confident is the confidence"). v1 ships scoring only —
the eventual AD-486 Holodeck consumer feeds outcomes through
``record_attempt(agent_id, capability, success)`` and queries
``get_confidence`` / ``get_calibration``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapabilityConfidence:
    """Per-(agent, capability) Beta(α, β) raw parameters.

    Mean confidence = alpha / (alpha + beta).
    Variance       = (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1)).
    """

    agent_id: str
    capability_category: str
    alpha: float
    beta: float

    @property
    def mean(self) -> float:
        denom = self.alpha + self.beta
        if denom <= 0.0:
            return 0.0
        return self.alpha / denom

    @property
    def variance(self) -> float:
        a, b = self.alpha, self.beta
        denom = (a + b) ** 2 * (a + b + 1)
        if denom <= 0.0:
            return 0.0
        return (a * b) / denom


class CapabilityConfidenceScorer:
    """Beta(α, β) accumulator, per-agent per-capability. AD-512e v1.

    Public API:
        record_attempt(agent_id, capability, success) -> CapabilityConfidence
        get_confidence(agent_id, capability) -> CapabilityConfidence
        list_for_agent(agent_id) -> tuple[CapabilityConfidence, ...]
        reset(agent_id, capability) -> None
    """

    def __init__(
        self,
        *,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
    ) -> None:
        if prior_alpha <= 0.0 or prior_beta <= 0.0:
            raise ValueError("prior_alpha and prior_beta must be > 0")
        self._prior_alpha = prior_alpha
        self._prior_beta = prior_beta
        # key: (agent_id, capability_category) -> (alpha, beta)
        self._params: dict[tuple[str, str], tuple[float, float]] = {}
        self.emit_event: Callable[..., None] | None = None

    def record_attempt(
        self,
        agent_id: str,
        capability_category: str,
        success: bool,
    ) -> CapabilityConfidence:
        """Increment α on success, β on failure. Returns updated confidence."""
        key = (agent_id, capability_category)
        a, b = self._params.get(key, (self._prior_alpha, self._prior_beta))
        if success:
            a += 1.0
        else:
            b += 1.0
        self._params[key] = (a, b)
        conf = CapabilityConfidence(
            agent_id=agent_id,
            capability_category=capability_category,
            alpha=a,
            beta=b,
        )
        self._emit_updated(conf)
        return conf

    def get_confidence(
        self,
        agent_id: str,
        capability_category: str,
    ) -> CapabilityConfidence:
        """Return current confidence (prior if no attempts recorded)."""
        key = (agent_id, capability_category)
        a, b = self._params.get(key, (self._prior_alpha, self._prior_beta))
        return CapabilityConfidence(
            agent_id=agent_id,
            capability_category=capability_category,
            alpha=a,
            beta=b,
        )

    def list_for_agent(self, agent_id: str) -> tuple[CapabilityConfidence, ...]:
        out: list[CapabilityConfidence] = []
        for (aid, cat), (a, b) in self._params.items():
            if aid != agent_id:
                continue
            out.append(CapabilityConfidence(
                agent_id=aid, capability_category=cat, alpha=a, beta=b,
            ))
        return tuple(out)

    def reset(self, agent_id: str, capability_category: str) -> None:
        """Drop the (agent, capability) record. Caller decides when."""
        self._params.pop((agent_id, capability_category), None)

    def _emit_updated(self, conf: CapabilityConfidence) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.CAPABILITY_CONFIDENCE_UPDATED,
                {
                    "agent_id": conf.agent_id,
                    "capability_category": conf.capability_category,
                    "alpha": conf.alpha,
                    "beta": conf.beta,
                    "mean": conf.mean,
                    "variance": conf.variance,
                },
            )
        except Exception:
            logger.warning(
                "AD-512e: emit_event failed for agent_id=%s; continuing",
                conf.agent_id,
                exc_info=True,
            )
===END FILE===
```

---

## Section 7 — ZPDCalibrator (AD-512f)

### File: `src/probos/crew_development/discovery/zpd.py`

```text
===FILE: src/probos/crew_development/discovery/zpd.py===
"""Vygotsky Zone of Proximal Development calibrator (AD-512f v1).

Selects discovery scenarios calibrated to an agent's edge of current
ability — neither so easy that no learning occurs nor so hard that the
agent founders without scaffolding.

ZPD band is anchored on the agent's current confidence mean
(``CapabilityConfidence.mean``) and a configurable lower/upper offset.
Scenarios whose ``difficulty`` falls inside the band are returned.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from probos.crew_development.discovery.confidence import CapabilityConfidence
from probos.crew_development.discovery.scenarios import DiscoveryScenario
from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ZPDBand:
    """A difficulty band for an agent in a capability category. AD-512f v1.

    ``difficulty_low`` and ``difficulty_high`` are inclusive bounds on
    [0.0, 1.0]. ``scaffolding_hint`` is a string suggestion for the
    eventual presenter (``high`` / ``medium`` / ``low`` / ``none``).
    """

    agent_id: str
    capability_category: str
    confidence_mean: float
    difficulty_low: float
    difficulty_high: float
    scaffolding_hint: str


class ZPDCalibrator:
    """Selects scenarios within an agent's Zone of Proximal Development. AD-512f v1.

    Public API:
        compute_band(confidence, *, lower_offset, upper_offset) -> ZPDBand
        select_scenarios(confidence, scenarios, *, lower_offset, upper_offset)
            -> tuple[DiscoveryScenario, ...]
    """

    def __init__(
        self,
        *,
        lower_offset: float = 0.40,
        upper_offset: float = 0.75,
    ) -> None:
        if not 0.0 <= lower_offset < upper_offset <= 1.0:
            raise ValueError(
                "lower_offset must be in [0,1) and strictly less than upper_offset (which must be ≤ 1)"
            )
        self._lower_offset = lower_offset
        self._upper_offset = upper_offset
        self.emit_event: Callable[..., None] | None = None

    def compute_band(
        self,
        confidence: CapabilityConfidence,
        *,
        lower_offset: float | None = None,
        upper_offset: float | None = None,
    ) -> ZPDBand:
        """Compute the difficulty band relative to current confidence mean."""
        lo = lower_offset if lower_offset is not None else self._lower_offset
        hi = upper_offset if upper_offset is not None else self._upper_offset
        mean = confidence.mean
        # Difficulty band is anchored ABOVE current ability — Vygotsky:
        # the ZPD is what the learner can do with scaffolding, beyond
        # what they can do alone.
        difficulty_low = max(0.0, min(1.0, mean + (lo - 0.5)))
        difficulty_high = max(0.0, min(1.0, mean + (hi - 0.5)))
        # Lower mean → higher scaffolding need.
        if mean < 0.30:
            scaffolding_hint = "high"
        elif mean < 0.60:
            scaffolding_hint = "medium"
        elif mean < 0.85:
            scaffolding_hint = "low"
        else:
            scaffolding_hint = "none"
        band = ZPDBand(
            agent_id=confidence.agent_id,
            capability_category=confidence.capability_category,
            confidence_mean=mean,
            difficulty_low=difficulty_low,
            difficulty_high=difficulty_high,
            scaffolding_hint=scaffolding_hint,
        )
        self._emit_calibrated(band)
        return band

    def select_scenarios(
        self,
        confidence: CapabilityConfidence,
        scenarios: tuple[DiscoveryScenario, ...],
        *,
        lower_offset: float | None = None,
        upper_offset: float | None = None,
    ) -> tuple[DiscoveryScenario, ...]:
        """Filter scenarios to those within the agent's ZPD band.

        Filters by ``capability_category == confidence.capability_category``
        AND ``difficulty_low <= scenario.difficulty <= difficulty_high``.
        """
        band = self.compute_band(
            confidence,
            lower_offset=lower_offset,
            upper_offset=upper_offset,
        )
        out = tuple(
            s for s in scenarios
            if s.capability_category == confidence.capability_category
            and band.difficulty_low <= s.difficulty <= band.difficulty_high
        )
        return out

    def _emit_calibrated(self, band: ZPDBand) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.ZPD_SCENARIO_CALIBRATED,
                {
                    "agent_id": band.agent_id,
                    "capability_category": band.capability_category,
                    "confidence_mean": band.confidence_mean,
                    "difficulty_low": band.difficulty_low,
                    "difficulty_high": band.difficulty_high,
                    "scaffolding_hint": band.scaffolding_hint,
                },
            )
        except Exception:
            logger.warning(
                "AD-512f: emit_event failed for agent_id=%s; continuing",
                band.agent_id,
                exc_info=True,
            )
===END FILE===
```

---

## Section 8 — Crew development package re-exports

### File: `src/probos/crew_development/__init__.py`

Confirm the existing file contents at HEAD and append AD-512 re-exports adjacent to the existing AD-507/509 re-exports. (Verify-first: read the file before applying.) Apply this block only if the existing pattern matches; otherwise skip and rely on `from probos.crew_development.discovery import ...` (the registries are wired by the wirer regardless of package-level re-exports).

```text
===MODIFY: src/probos/crew_development/__init__.py===
===SEARCH===
from probos.crew_development.boot_camp import (
    AgentBootCampRecord,
    BootCampPhase,
    BootCampPhaseTracker,
)

__all__ = [
    "CoreKnowledgeCurriculumRegistry",
    "CurriculumModule",
    "AgentBootCampRecord",
    "BootCampPhase",
    "BootCampPhaseTracker",
]
===REPLACE===
from probos.crew_development.boot_camp import (
    AgentBootCampRecord,
    BootCampPhase,
    BootCampPhaseTracker,
)
from probos.crew_development.discovery import (
    CapabilityConfidence,
    CapabilityConfidenceScorer,
    CrossFunctionalSuggestion,
    DiscoveryScenario,
    DiscoveryScenarioRegistry,
    StrengthMap,
    StrengthRecord,
    ZPDBand,
    ZPDCalibrator,
    frame_as_discovery,
    frame_as_growth,
    suggest_routing,
)

__all__ = [
    "CoreKnowledgeCurriculumRegistry",
    "CurriculumModule",
    "AgentBootCampRecord",
    "BootCampPhase",
    "BootCampPhaseTracker",
    "CapabilityConfidence",
    "CapabilityConfidenceScorer",
    "CrossFunctionalSuggestion",
    "DiscoveryScenario",
    "DiscoveryScenarioRegistry",
    "StrengthMap",
    "StrengthRecord",
    "ZPDBand",
    "ZPDCalibrator",
    "frame_as_discovery",
    "frame_as_growth",
    "suggest_routing",
]
===END REPLACE===
```

Verified anchor: `src/probos/crew_development/__init__.py:17-29` has the parenthesized `from probos.crew_development.boot_camp import (...)` block and `__all__` list. The SEARCH/REPLACE applies cleanly to that exact shape.

---

## Section 9 — Finalize wirer

### File: `src/probos/startup/finalize.py`

Insert `_wire_discovery_learning` immediately after `_wire_boot_camp_tracker`:

```text
===MODIFY: src/probos/startup/finalize.py===
===SEARCH===
def _wire_boot_camp_tracker(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-509 v1: Wire BootCampPhaseTracker (in-memory observational)."""
    cfg = getattr(config, "boot_camp_phase", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.crew_development.boot_camp import BootCampPhaseTracker

    emit_fn = getattr(runtime, "emit_event", None)
    tracker = BootCampPhaseTracker()
    tracker.emit_event = emit_fn
    runtime.boot_camp_tracker = tracker  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-509: Boot Camp Phase Tracker v1 initialized (5 phases + COMPLETED; observational)"
    )
    return True
===REPLACE===
def _wire_boot_camp_tracker(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-509 v1: Wire BootCampPhaseTracker (in-memory observational)."""
    cfg = getattr(config, "boot_camp_phase", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.crew_development.boot_camp import BootCampPhaseTracker

    emit_fn = getattr(runtime, "emit_event", None)
    tracker = BootCampPhaseTracker()
    tracker.emit_event = emit_fn
    runtime.boot_camp_tracker = tracker  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-509: Boot Camp Phase Tracker v1 initialized (5 phases + COMPLETED; observational)"
    )
    return True


def _wire_discovery_learning(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-512 v1: Wire DiscoveryScenarioRegistry, StrengthMap,
    CapabilityConfidenceScorer, and ZPDCalibrator (observational substrate).
    """
    cfg = getattr(config, "discovery_learning", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.crew_development.discovery import (
        CapabilityConfidenceScorer,
        DiscoveryScenarioRegistry,
        StrengthMap,
        ZPDCalibrator,
    )

    emit_fn = getattr(runtime, "emit_event", None)

    scenario_registry = DiscoveryScenarioRegistry()
    scenario_registry.emit_event = emit_fn
    runtime.discovery_scenario_registry = scenario_registry  # public (Wave 5 conv #1)

    strength_map = StrengthMap()
    strength_map.emit_event = emit_fn
    runtime.strength_map = strength_map  # public (Wave 5 conv #1)

    confidence_scorer = CapabilityConfidenceScorer(
        prior_alpha=cfg.confidence_prior_alpha,
        prior_beta=cfg.confidence_prior_beta,
    )
    confidence_scorer.emit_event = emit_fn
    runtime.capability_confidence_scorer = confidence_scorer  # public (Wave 5 conv #1)

    zpd_calibrator = ZPDCalibrator(
        lower_offset=cfg.zpd_lower_bound,
        upper_offset=cfg.zpd_upper_bound,
    )
    zpd_calibrator.emit_event = emit_fn
    runtime.zpd_calibrator = zpd_calibrator  # public (Wave 5 conv #1)

    logger.info(
        "AD-512: Discovery Learning v1 initialized "
        "(%d scenarios; Beta(α=%.2f, β=%.2f) priors; ZPD band [%.2f, %.2f])",
        len(scenario_registry.list_scenarios()),
        cfg.confidence_prior_alpha,
        cfg.confidence_prior_beta,
        cfg.zpd_lower_bound,
        cfg.zpd_upper_bound,
    )
    return True
===END REPLACE===
```

Add wirer dispatch immediately after the `_wire_boot_camp_tracker` invocation:

```text
===MODIFY: src/probos/startup/finalize.py===
===SEARCH===
    if _wire_boot_camp_tracker(runtime=runtime, config=config):
        logger.info("AD-509: Boot Camp Phase Tracker v1 wired during finalization")

    if _wire_ship_state_snapshot(runtime=runtime, config=config):
===REPLACE===
    if _wire_boot_camp_tracker(runtime=runtime, config=config):
        logger.info("AD-509: Boot Camp Phase Tracker v1 wired during finalization")

    if _wire_discovery_learning(runtime=runtime, config=config):
        logger.info("AD-512: Discovery Learning v1 wired during finalization")

    if _wire_ship_state_snapshot(runtime=runtime, config=config):
===END REPLACE===
```

---

## Section 10 — Tests

### File: `tests/test_ad512_discovery_learning.py`

32 tests across 8 classes. Standard pytest + `_FakeEmit` capture pattern. No `MagicMock`. No async (this AD has zero async paths).

Test class layout (counts and names; Builder produces full bodies):

```text
class TestDiscoveryScenarioRegistry:           # 4 tests
    test_default_catalog_seeds_8_scenarios
    test_get_scenario_emits_offered_event
    test_list_by_category_filters_correctly
    test_list_by_difficulty_band_inclusive_bounds

class TestStrengthMap:                          # 6 tests
    test_record_outcome_appends_record
    test_record_outcome_emits_outcome_and_map_updated
    test_get_strengths_threshold_respected
    test_get_struggles_threshold_respected
    test_min_attempts_gate_excludes_low_attempts
    test_to_episode_payload_has_importance_8_and_source

class TestCrossFunctionalSuggestion:            # 3 tests
    test_struggle_yields_strengthen_suggestion
    test_success_yields_no_strengthen_suggestion
    test_rationale_includes_agent_and_scenario

class TestGrowthMindsetFraming:                 # 4 tests
    test_frame_as_growth_rewrites_cant
    test_frame_as_growth_idempotent
    test_frame_as_growth_unrecognized_prefix_unchanged
    test_frame_as_discovery_wraps_struggle

class TestCapabilityConfidenceScorer:           # 5 tests
    test_default_prior_returns_mean_half
    test_record_attempt_success_increments_alpha
    test_record_attempt_failure_increments_beta
    test_emit_capability_confidence_updated
    test_invalid_prior_raises

class TestZPDCalibrator:                        # 4 tests
    test_compute_band_low_confidence_yields_high_scaffolding
    test_compute_band_high_confidence_yields_no_scaffolding
    test_select_scenarios_filters_by_difficulty_and_category
    test_invalid_offsets_raise

class TestDiscoveryLearningConfig:              # 3 tests
    test_default_enabled_true
    test_zpd_band_validator_rejects_inverted
    test_prior_alpha_zero_rejected

class TestWiringIntegration:                    # 3 tests
    test_wirer_disabled_returns_false
    test_wirer_enabled_attaches_four_attrs
    test_wirer_passes_priors_into_scorer
```

Test fixtures the file shares:

```python
class _FakeEmit:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


def _make_record(
    *,
    agent_id: str = "tau",
    scenario_id: str = "diagnose_simple_fault",
    capability_category: str = "diagnosis",
    success: bool = True,
    confidence_self_report: float = 0.5,
    timestamp: float = 1000.0,
    notes: str = "",
) -> StrengthRecord:
    return StrengthRecord(...)
```

`TestWiringIntegration` uses a minimal stub runtime + a `SystemConfig()` instance (real config, not a mock) per the standing-order rule "tests pass real `Config()` instances."

---

## What this AD does NOT change

- **No HXI surface.** Discovery panel deferred to AD-512-HXI follow-on.
- **No router / API endpoints.** Substrate is internal-only in v1; future AD adds REST surface.
- **No new Intent.** No DAG dispatch path touched.
- **No LLM call.** Substrate has zero LLM dependency.
- **No Hebbian writes from this module.** `suggest_routing` returns the tuple shape only; the (eventual) AD-486 Holodeck consumer calls `runtime.hebbian_router.record_interaction(...)`.
- **No EpisodicMemory writes from this module.** `to_episode_payload` returns a dict shape; caller constructs Episode and calls `EpisodicMemory.store()`.
- **No PersonalOntologyProber subscription.** AD-487 `STRENGTH_MAP_UPDATED` listener is reserved for AD-487b — not in v1.
- **No SystemQAAgent involvement.** Discovery is observational learning, not validation.
- **No new Pool / Spawner template.** No agent instances introduced.
- **No federation export.** Discovery records are agent-local in v1; federation is AD-512g territory.
- **No persistence.** Strength map and confidence scorer are in-memory only; restart drops state. Persistence is AD-512h territory (would compose with AD-487 PersonalOntologyProber's existing SQLite handle).
- **No HolodeckRunner module.** AD-486 is the Holodeck wave; v1 ships substrate only.
- **No AD-507/509/511 v1 substrate edits.** Curriculum registry, boot-camp tracker, autonomy boundaries unchanged.
- **No new EventType beyond the 5 listed.** Adjacent AD-509 / AD-522 enums unchanged.

---

## Tracking

- `PROGRESS.md` — open `## Wave 84` entry under the latest `## Wave 83 (closed)` block; mark `AD-512 v1 PENDING` on draft commit, flip to `AD-512 v1 CLOSED` after Builder lands.
- `docs/development/roadmap.md` line 6407 — flip the `*(planned, OSS, depends: AD-507, AD-486)*` tag to `*(v1 partial — Discovery Learning substrate shipped Wave 84; Holodeck consumer deferred to AD-486)*`. Sub-AD letter list (a–f) added to mirror the AD-507 / AD-509 / AD-511 v1 partial pattern.
- `DECISIONS.md` — append `### AD-512 v1: Discovery-Based Capability Building Substrate (2026-05-06)` with one-paragraph rationale (no breaking change; observational substrate).
- `prompts/wave-plan.yaml` — append wave 84 entry per Section 11.
- `prompts/Reviews/ad-512-discovery-learning-v1-review.md` — Architect's 4-pass review record (created during draft-review cycle).

---

## Acceptance Criteria

1. New package `src/probos/crew_development/discovery/` containing 6 modules + `__init__.py` re-exports.
2. 5 new EventType values in `events.py` adjacent to AD-509 block.
3. `DiscoveryLearningConfig` Pydantic model (default-True, AD-507/509/511 precedent) with `model_validator(mode="after")` enforcing `zpd_lower_bound < zpd_upper_bound`. `SystemConfig.discovery_learning` field.
4. `_wire_discovery_learning(*, runtime, config) -> bool` in `startup/finalize.py` immediately after `_wire_boot_camp_tracker`. Wirer dispatch added at the same call site.
5. 4 new public runtime attributes (`runtime.discovery_scenario_registry`, `runtime.strength_map`, `runtime.capability_confidence_scorer`, `runtime.zpd_calibrator`) populated by the wirer.
6. 32 new tests in `tests/test_ad512_discovery_learning.py` across 8 classes; all pass.
7. Baseline 11673 → ≥ 11703 (Δ ≥ +30); 32 tests planned, +30 floor leaves 2-test margin for parametrize fan-out variance.
8. No HXI / router / Intent / LLM-call / Hebbian-write / Episode-write surface changes outside the new package and 5-line wirer hook.
9. Pre-commit hook clean: zero hits on the e-word-plus-tier banned phrase and zero hits on the private-commercial-repo path-token banned phrase across `prompts/WAVE-84-DISPATCH.md` + this prompt + `Reviews/`.
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
11. GH issue #94 closed with the AD-512 v1 closure note.

---

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  7504430

# Highest AD stem at HEAD (no new AD minted by this wave; AD-512 pre-allocated by roadmap line 6407):
docs/development/roadmap.md:6407
  AD-512: Discovery-Based Capability Building — Experiential Learning Over Instruction (planned, OSS, depends: AD-507, AD-486)
docs/development/roadmap.md:7191
  AD-696 (Wave 72 Oracle agentic retrieval — last assigned)

# Existing crew-development substrate (verified shipped — pattern source):
src/probos/crew_development/curriculum.py:151    class CoreKnowledgeCurriculumRegistry
src/probos/crew_development/boot_camp.py:62      class BootCampPhaseTracker
src/probos/security/autonomy_boundaries.py:31    class BoundaryDefinition
src/probos/cognitive/self_distillation/prober.py:66    class PersonalOntologyProber

# Existing wirer pattern (verified):
src/probos/startup/finalize.py:122   def _wire_curriculum_registry
src/probos/startup/finalize.py:141   def _wire_boot_camp_tracker
src/probos/startup/finalize.py:176   def _wire_autonomy_boundaries
src/probos/startup/finalize.py:1308-1312   dispatch block (curriculum + boot_camp + ship_state_snapshot)

# Existing config pattern (verified):
src/probos/config.py:2410   class CrewDevelopmentConfig
src/probos/config.py:2419   class BootCampPhaseConfig
src/probos/config.py:2607-2611   SystemConfig.crew_development / boot_camp_phase fields

# EventType insertion site (adjacent to AD-509):
src/probos/events.py:354   CURRICULUM_MODULE_QUERIED  # AD-507
src/probos/events.py:357   BOOT_CAMP_PHASE_ADVANCED   # AD-509
src/probos/events.py:359   SPC_RULE_VIOLATED          # AD-522 (next block — insertion anchor)

# Hebbian + Episode consumer surfaces (verified shipped — caller-driven only):
src/probos/mesh/routing.py:39    class HebbianRouter
src/probos/mesh/routing.py:177   def record_interaction(source, target, success, rel_type)
src/probos/cognitive/episodic.py:651    class EpisodicMemory
src/probos/cognitive/episodic.py:942    async def store(self, episode: Episode) -> None
src/probos/types.py:439   @dataclass(frozen=True) class Episode  (importance: int = 5)

# Greenfield (verified absent — no collision):
src/probos/crew_development/discovery/                     # does not exist
src/probos/crew_development/discovery/scenarios.py         # does not exist
src/probos/crew_development/discovery/strength_map.py      # does not exist
src/probos/crew_development/discovery/cross_functional.py  # does not exist
src/probos/crew_development/discovery/framing.py           # does not exist
src/probos/crew_development/discovery/confidence.py        # does not exist
src/probos/crew_development/discovery/zpd.py               # does not exist
tests/test_ad512_discovery_learning.py                     # does not exist
```

All concrete claims in this prompt map to a grep hit above. New entities introduced by this prompt's SEARCH/REPLACE blocks (5 EventTypes, `DiscoveryLearningConfig`, `_wire_discovery_learning`, 6 module classes, 4 public runtime attrs) are NOT flagged as missing — they are the migration.
