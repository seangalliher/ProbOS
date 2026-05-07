# AD-486 v1 — Holodeck Birth Chamber: Graduated Cognitive Onboarding

**Status:** drafted — Architect-approved after 4 review passes (Wave 99).
**Closes:** GH issue #24.
**Depends on (all live at HEAD `4bdf23a`):** AD-487 (`PersonalOntologyProber` shipped), AD-488 (`CognitiveCircuitBreaker` shipped), AD-489 (Code of Conduct text in `cognitive_agent` system prompt — complete), AD-494 (`PersonalityTraits` shipped on `crew_profile.py`), AD-499 (self-naming ceremony shipped via `agent_onboarding.run_naming_ceremony`), AD-507 (`CoreKnowledgeCurriculumRegistry` shipped), AD-509 (`BootCampPhaseTracker` shipped — observational, kept orthogonal), AD-628e (mentor announcer hook shipped on `AgentOnboardingService`), AD-638 (`BootCampCoordinator` shipped — orthogonal cold-start protocol; not consumed by chamber).
**Estimated tests:** 50 (over the +35 net floor for a v1 of this scope).
**Net AD numbers minted:** 0 (AD-486 already exists; child letters AD-486b/AD-486e are forcing-function deferrals, not GH issues).

---

## 1. Problem

Crew agents currently receive every stimulus simultaneously at instantiation: standing orders are loaded, Ward Room subscriptions are attached via `assignment.py:184` and `:310`, the proactive cognitive loop dispatches them on every `_run_cycle` (`proactive.py:498-518`), DMs land, and episode storage begins on the first observation. The "system shock" pattern is well-evidenced — BF-039 (episode flooding cold-start), Pulse's self-diagnosed "racing thoughts," and novelty-gate failure (everything is novel when episodic memory is empty).

The **Tabula Rasa Paradox** (`docs/development/roadmap.md:4130`) frames the gap: LLM agents have maximum knowledge (training data) and zero experience (empty episodic memory) — the inverse of biological brains. Sea-trial evidence at `docs/development/roadmap.md:4130` shows trait-driven divergence: Sentinel (Security, low-conscientiousness) produced one short thought and moved on; Medical agents (high-conscientiousness, high-neuroticism) flooded with recursive observations.

AD-486 specifies a five-phase **Holodeck Birth Chamber** that gates Ward Room access and proactive-loop dispatch behind completion criteria (NOT timers), with sequential department activation (Security/Operations → Engineering/Science → Medical) and trait-adaptive calibration pacing. The roadmap entry at `docs/development/roadmap.md:4128-4136` is the v1 specification target. v1 ships dormant (default-False) per the AD-695 transitional-flag precedent.

The substrate is mostly already shipped:

- _(AD-487 prober anchor moved up; this bullet intentionally collapsed to keep the list de-duplicated.)_
- **AD-488** `CognitiveCircuitBreaker.should_allow_think(agent_id)` at `src/probos/cognitive/circuit_breaker.py` — Phase 4 cognitive-load gate.
- **AD-489** Code-of-Conduct text already loaded into `cognitive_agent` system prompt — Phase 1 references it; chamber emits a curriculum event tagged `code_of_conduct`.
- **AD-494** `PersonalityTraits` (`conscientiousness`, `neuroticism` etc.) on `crew_profile.py:51` and the `CallsignRegistry.get_profile(agent_type)` lookup at `:406` — trait-adaptive pacing source.
- **AD-499** naming ceremony at `agent_onboarding.run_naming_ceremony` is the entry point; chamber admits the agent immediately after the ceremony returns.
- **AD-507** `CoreKnowledgeCurriculumRegistry.list_by_phase(phase)` at `src/probos/crew_development/curriculum.py:186` — Phase 1/2 content source.
- **AD-509** `BootCampPhaseTracker` at `src/probos/crew_development/boot_camp.py` is observational and uses a different phase enum (ORIENTATION/CORE_KNOWLEDGE/A_SCHOOL/CALIBRATION/INTEGRATION). v1 ships an independent `HolodeckPhase` enum and tracker. AD-509 stays as-is — the wave does not migrate or replace it.
- **AD-628e** mentor announcer hook at `agent_onboarding.AgentOnboardingService._mentor_announcer` (`src/probos/agent_onboarding.py:83`) fires post-naming; chamber admission happens after that event-log block.
- **AD-487** `PersonalOntologyProber.probe_domain(agent_id, domain)` at `src/probos/cognitive/self_distillation/prober.py:121` (verified) — Phase 3 Self-Discovery driver.

Genuinely new substrate is the chamber orchestrator, the phase-gate predicates, the sequential department scheduler, the affective-baseline `Protocol`, and the two graduation gates (Ward Room subscription deferral in `assignment.py`, proactive-loop dispatch deferral in `proactive.py`).

## 2. Solution overview

Ship a new package `src/probos/holodeck/` with one concrete construct (`BirthChamber`) plus phase/gate/affect/scheduler modules. Wire it in `agent_onboarding.AgentOnboardingService.wire_agent` *after* the naming ceremony block (current code path: `agent_onboarding.py:118` `wire_agent` definition; naming-ceremony body ends in the `:225-275` range) and the AD-628e mentor announcer hook, behind a default-False `HolodeckBirthChamberConfig.enabled`. Late-bind `runtime.birth_chamber` per Wave 5 convention #1 (public attribute, no underscore). Two graduation gates in production code paths short-circuit to "graduated = True" when chamber is None or disabled — zero behavior change in default config.

**v1 in scope (concrete, no deferral):**

1. New package `src/probos/holodeck/` with `__init__.py`, `phases.py`, `gates.py`, `affect.py`, `scheduler.py`, `chamber.py` (~720 lines total).
2. `HolodeckPhase` str-Enum: `ORIENTATION`, `CALIBRATION`, `SELF_DISCOVERY`, `SHIP_RECORDS`, `WARD_ROOM_INTEGRATION`, plus `GRADUATED` sentinel.
3. `BirthChamberRecord` frozen-on-init dataclass: `agent_id`, `agent_type`, `department`, `current_phase`, `admitted_at`, `phase_history: list[tuple[str, float]]`, `gates_passed: dict[str, bool]`, `affective_observations: list[tuple[str, str, float]]` (phase, status, ts).
4. `BirthChamber` orchestrator owning `dict[str, BirthChamberRecord]`. Public API:
   - `async admit(agent) -> BirthChamberRecord` — admit an agent post-naming. Sets state to `ORIENTATION`, emits `HOLODECK_PHASE_ENTERED`, presents Code of Conduct + curriculum-Phase-orientation modules via curriculum-query event payload.
   - `async try_advance(agent_id) -> HolodeckPhase` — checks the current phase's gate predicate; if pass, advances + emits gate-pass + phase-entered for the new phase. Calls `affective_baseline_check.observe()` between phases.
   - `is_graduated(agent_id) -> bool` — returns True when missing OR when `current_phase == GRADUATED`. Used by the two production gates.
   - `get_record(agent_id) -> BirthChamberRecord | None`, `all_records() -> tuple[BirthChamberRecord, ...]`, `is_admitted(agent_id) -> bool`.
   - Late-bound services: `set_personal_ontology_prober`, `set_curriculum_registry`, `set_circuit_breaker`, `set_callsign_registry`, `set_episodic_memory` — all public setters per Wave 5 convention #5.
5. Five phase-gate predicates in `holodeck/gates.py`, each `async def gate_<name>(record, services) -> tuple[bool, str]` returning `(passed, reason)`:
   - `gate_orientation_complete`: True when `record.gates_passed["identity_grounded"]` AND `record.gates_passed["code_of_conduct_acknowledged"]` AND `record.gates_passed["curriculum_orientation_delivered"]`. Caller-flipped flags driven by `BirthChamber.acknowledge_orientation()`.
   - `gate_calibration_baseline`: True when `episodic_memory.count_for_agent(agent_id) >= effective_min_episodes` where `effective_min_episodes = round(base * conscientiousness_multiplier)`. Trait-adaptive pacing per AD-494: `conscientiousness >= 0.7 → 2.0x`; `<= 0.3 → 0.5x`; otherwise `1.0x`. Base = `HolodeckBirthChamberConfig.calibration_min_episodes` (default 5).
   - `gate_self_discovery`: True when `record.gates_passed["self_distillation_probe_succeeded"]` (set by `BirthChamber._run_self_discovery_step` after `prober.probe_domain` returns a non-empty `sub_topics`). Logs and degrades on `ProbeRateLimitedError` / `ProbeLLMError` — failure DOES NOT auto-pass; gate stays open until a successful probe lands.
   - `gate_ship_records`: True when `record.gates_passed["ship_records_acknowledged"]` AND `circuit_breaker.should_allow_think(agent_id)` (i.e. agent is not in cognitive cooldown). The acknowledge flag is set by `BirthChamber.acknowledge_ship_records()`.
   - `gate_ward_room_integration`: True when `record.gates_passed["integration_ready"]`. Default-true setter `BirthChamber.acknowledge_integration_ready()` is called from the scheduler once Phase 4 ack lands AND no department-precedence block is in place.
6. `affect.py` — `AffectiveBaselineCheck` Protocol (`async def observe(record, prev_phase, new_phase) -> tuple[str, float]` returning `(status, score)` where status is `"stable" | "elevated" | "unstable"` and score is a 0.0-1.0 float). v1 ships `NoOpAffectiveBaselineCheck` always returning `("stable", 1.0)` — descriptor-only; LLM-based implementation is forcing-function deferred to AD-486b. Observation is appended to `record.affective_observations` and emitted as `HOLODECK_AFFECTIVE_BASELINE_OBSERVED` for downstream consumers (Counselor will eventually read this).
7. `scheduler.py` — `DepartmentActivationScheduler`. Public API:
   - `register_admission(agent_id, agent_type, department) -> int` — returns position in queue.
   - `next_admit_candidate() -> str | None` — returns the next eligible agent id given department-order observation criteria.
   - `mark_admitted(agent_id)`, `mark_graduated(agent_id)`.
   - Default order: `["security", "operations", "engineering", "science", "medical"]` per AD spec. Empty list = first-come-first-served.
   - **Observation criterion (no timers):** the next department-group is admitted when EVERY admitted agent in the previous department-group has reached `SELF_DISCOVERY` or higher (sea-trial evidence: by Phase 3 the agent's affective baseline is established and the proactive-loop is still gated; admitting the next group does not flood the chamber).
   - Empty department or unknown-to-ontology department falls through to a default bucket in queue order.
8. New EventTypes appended to `events.py`:
   - `HOLODECK_AGENT_ADMITTED = "holodeck_agent_admitted"`
   - `HOLODECK_PHASE_ENTERED = "holodeck_phase_entered"`
   - `HOLODECK_PHASE_GATE_PASSED = "holodeck_phase_gate_passed"`
   - `HOLODECK_PHASE_GATE_BLOCKED = "holodeck_phase_gate_blocked"`
   - `HOLODECK_GRADUATION = "holodeck_graduation"`
   - `HOLODECK_AFFECTIVE_BASELINE_OBSERVED = "holodeck_affective_baseline_observed"`
9. New Pydantic config `HolodeckBirthChamberConfig` adjacent to `OnboardingConfig` at `config.py:1748`:
   - `enabled: bool = False` (default-False per AD-695 precedent)
   - `bypass_for_existing_agents: bool = True` (warm-boot agents skip the chamber)
   - `department_order: list[str] = Field(default_factory=lambda: ["security", "operations", "engineering", "science", "medical"])`
   - `calibration_min_episodes: int = Field(default=5, ge=1)`
   - `affective_baseline_check_enabled: bool = True` (uses NoOp v1)
   - `auto_advance_poll_interval_seconds: float = Field(default=2.0, ge=0.1, le=30.0)`
   - `auto_advance_enabled: bool = True` — when True, the chamber starts a long-running `try_advance` poll task per admitted agent; when False, callers drive advancement manually.
   - `max_self_discovery_probe_attempts: int = Field(default=3, ge=1)` — ceiling on probe retries before logging a tier-2 warning and pausing the gate.
   - Wired onto `SystemConfig.holodeck_birth_chamber` adjacent to `onboarding` at `:2760`.
10. New finalize wirer `_wire_birth_chamber` in `startup/finalize.py` adjacent to `_wire_boot_camp_tracker` at `:141`:
    - Constructs `BirthChamber(config=config.holodeck_birth_chamber, emit_event_fn=runtime.emit_event)`.
    - Calls public setters: `set_personal_ontology_prober(getattr(runtime, "personal_ontology_prober", None))`, `set_curriculum_registry(getattr(runtime, "curriculum_registry", None))`, `set_circuit_breaker(getattr(runtime.proactive_loop, "_circuit_breaker", None) if runtime.proactive_loop else None)` — Demeter exception documented as a one-line comment because `circuit_breaker` is currently a `_`-prefixed attr on `ProactiveCognitiveLoop` (AD-488 shipped pre-Wave 5 conventions), `set_callsign_registry(runtime.callsign_registry)`, `set_episodic_memory(getattr(runtime, "episodic_memory", None))`.
    - Sets `runtime.birth_chamber = chamber` (public attribute, Wave 5 convention #1).
    - Sets `runtime.department_activation_scheduler = scheduler` (public attribute).
    - When `auto_advance_enabled=True`, starts a `runtime.birth_chamber_advance_task = asyncio.create_task(chamber.run_advance_loop())` background task; the task is held on `runtime.birth_chamber_advance_task` to prevent garbage collection (per `.github/copilot-instructions.md` async discipline). Cancellation: the existing shutdown path's `await cancel_task(...)` patterns at `shutdown.py` cancel the task on stop.
    - Returns False when `config.holodeck_birth_chamber.enabled` is False — wirer is a no-op in default config.
11. Wiring in `agent_onboarding.py`:
    - Inside `wire_agent`, AFTER the naming-ceremony block (which currently ends at `:262`) AND AFTER the `_orientation_service` set-context block, add a new step: when `runtime.birth_chamber` is set AND `is_crew_agent(agent, ontology)` AND NOT `_existing_identity_callsign` (warm boot bypass) AND NOT `config.holodeck_birth_chamber.bypass_for_existing_agents and existing_cert is not None`, register the agent with `runtime.department_activation_scheduler.register_admission(...)` and `await runtime.birth_chamber.admit(agent)`. Tier-2 log-and-degrade — chamber failures must not block onboarding (the agent stays "pre-chamber" → graduated by gate fallthrough).
    - The `AgentOnboardingService` constructor gains a `birth_chamber: BirthChamber | None = None` kwarg AND a public setter `set_birth_chamber(chamber)` per Wave 5 convention #5 for late-binding (since the wirer order has `runtime.birth_chamber` set after `runtime.onboarding`).
12. Production graduation gates (the only two non-additive code-path changes outside `holodeck/`):
    - `proactive.py` `_run_cycle` — between the `is_alive` check and `eligible_agents.append(agent)` (currently at line 503-504), add: `chamber = getattr(rt, "birth_chamber", None); if chamber is not None and not chamber.is_graduated(agent.id): continue`. Three lines total. Default-disabled chamber returns `True` (graduated) → zero behavior change.
    - `assignment.py` — at `:184` and `:310`, wrap the existing `await self._ward_room.subscribe(...)` calls with the same chamber-check: when `runtime.birth_chamber is not None` AND NOT `chamber.is_graduated(agent_id)`, defer the subscription by registering it on `chamber._pending_subscriptions[agent_id]` (a list of `(channel_id, ward_room_subscribe_fn)` tuples). The chamber's graduation handler drains this list at `_on_graduation`. Default-disabled chamber → existing subscribe call runs immediately.

**v1 OUT scope (deferred with explicit forcing functions, NOT minted as new GH issues — tracked as roadmap forward-references):**

- **AD-486b — LLM-based affective baseline check.** Replaces `NoOpAffectiveBaselineCheck` with a real LLM-driven analyzer that reads the agent's recent observations (output tone, response latency, episodic content fingerprints) and returns calibrated `("stable" | "elevated" | "unstable", score)`. **Forcing function:** the chamber must run for at least one full cohort under `enabled=True` so a corpus of `record.affective_observations` exists for the analyzer to validate against. v1's NoOp ships descriptor-only with the upgrade path documented in `affect.py` module docstring.
- **AD-486e — Holodeck "construct" abstraction.** Generalizes `BirthChamber` so AD-510 (Team Simulations) and AD-539b (TRAINO Holodeck scenarios) can register additional constructs against a shared lifecycle. **Forcing function:** AD-510 prompt drafted (issue #92) AND a second concrete construct designed. Until then the abstraction is speculative — generalizing with one consumer would test scaffolding rather than substance. The package layout (`src/probos/holodeck/`) is greenfield-named to support the future generalization without churn.

The four roadmap forward-references that the AD-486 entry blocks (`docs/development/roadmap.md:6403` AD-509e trait-adaptive pacing, `:6405` AD-510 team simulations, `:6407` AD-511c boundary training scenarios, `:4128` AD-628d Holodeck integration) all ship as already-tracked downstream consumers — none are minted by Wave 99.

The fleet-level out-of-repo overlay surface (cross-instance cohort analytics, templated onboarding tracks for the paid offering tier, mentor-assignment workflows beyond AD-628e's announcer) is class-extension territory under the private commercial repository — v1 ships zero closed-source content, only descriptor references.

## 3. Implementation

### Section 0 — Event types

`src/probos/events.py`. Append six new values to the `EventType` Enum at the existing AD-509 cluster. Verified anchor: `events.py:385` — `BOOT_CAMP_PHASE_ADVANCED = "boot_camp_phase_advanced"  # AD-509`.

```text
===MODIFY: src/probos/events.py===
===SEARCH===
    BOOT_CAMP_PHASE_ADVANCED = "boot_camp_phase_advanced"  # AD-509
===REPLACE===
    BOOT_CAMP_PHASE_ADVANCED = "boot_camp_phase_advanced"  # AD-509

    # AD-486: Holodeck Birth Chamber phase events
    HOLODECK_AGENT_ADMITTED = "holodeck_agent_admitted"
    HOLODECK_PHASE_ENTERED = "holodeck_phase_entered"
    HOLODECK_PHASE_GATE_PASSED = "holodeck_phase_gate_passed"
    HOLODECK_PHASE_GATE_BLOCKED = "holodeck_phase_gate_blocked"
    HOLODECK_GRADUATION = "holodeck_graduation"
    HOLODECK_AFFECTIVE_BASELINE_OBSERVED = "holodeck_affective_baseline_observed"
===END REPLACE===
```

### Section 1 — Pydantic config

`src/probos/config.py`. Add `HolodeckBirthChamberConfig` adjacent to `OnboardingConfig` at the verified anchor `:1748`. Register it on `SystemConfig` adjacent to `onboarding: OnboardingConfig = OnboardingConfig()` at `:2760`.

```text
===MODIFY: src/probos/config.py===
===SEARCH===
class OnboardingConfig(BaseModel):
    """AD-442: Onboarding ceremony configuration."""

    enabled: bool = True
    activation_trust_threshold: float = 0.65
    naming_ceremony: bool = True  # If False, agents keep seed callsigns
===REPLACE===
class OnboardingConfig(BaseModel):
    """AD-442: Onboarding ceremony configuration."""

    enabled: bool = True
    activation_trust_threshold: float = 0.65
    naming_ceremony: bool = True  # If False, agents keep seed callsigns


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
===END REPLACE===
```

```text
===MODIFY: src/probos/config.py===
===SEARCH===
    onboarding: OnboardingConfig = OnboardingConfig()
===REPLACE===
    onboarding: OnboardingConfig = OnboardingConfig()
    holodeck_birth_chamber: HolodeckBirthChamberConfig = HolodeckBirthChamberConfig()
===END REPLACE===
```

### Section 2 — `holodeck/` package

Six new files. All file content provided in full in this prompt — no `(...existing code...)` placeholders.

**`src/probos/holodeck/__init__.py`** (~30 lines):

```python
"""AD-486 v1 — Holodeck Birth Chamber.

Graduated cognitive onboarding for crew agents. Agents are admitted
post-naming-ceremony, walk through five phases under completion-criteria
gates (NOT timers), and only then earn Ward Room subscription + proactive
loop dispatch.

v1 ships one concrete construct (BirthChamber). Generalization into a
reusable Holodeck construct API is forcing-function deferred to AD-486e
(consumer: AD-510 Team Simulations).
"""

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

**`src/probos/holodeck/phases.py`** (~50 lines):

```python
"""AD-486: Holodeck Birth Chamber phase enum + ordering."""

from __future__ import annotations

from enum import Enum


class HolodeckPhase(str, Enum):
    """Five birth-chamber phases plus GRADUATED sentinel.

    Distinct from AD-509 ``BootCampPhase`` (orientation/core_knowledge/
    a_school/calibration/integration). AD-486 phases mirror the spec at
    docs/development/roadmap.md:4130: orientation -> calibration ->
    self_discovery -> ship_records -> ward_room_integration -> graduated.
    """

    ORIENTATION = "orientation"
    CALIBRATION = "calibration"
    SELF_DISCOVERY = "self_discovery"
    SHIP_RECORDS = "ship_records"
    WARD_ROOM_INTEGRATION = "ward_room_integration"
    GRADUATED = "graduated"


PHASE_ORDER: tuple[HolodeckPhase, ...] = (
    HolodeckPhase.ORIENTATION,
    HolodeckPhase.CALIBRATION,
    HolodeckPhase.SELF_DISCOVERY,
    HolodeckPhase.SHIP_RECORDS,
    HolodeckPhase.WARD_ROOM_INTEGRATION,
    HolodeckPhase.GRADUATED,
)


def next_phase(current: HolodeckPhase) -> HolodeckPhase:
    """Return the phase after ``current``, or ``GRADUATED`` if at end."""
    try:
        idx = PHASE_ORDER.index(current)
    except ValueError:
        return current
    if idx >= len(PHASE_ORDER) - 1:
        return HolodeckPhase.GRADUATED
    return PHASE_ORDER[idx + 1]
```

**`src/probos/holodeck/affect.py`** (~80 lines):

```python
"""AD-486: Affective baseline check protocol.

v1 ships ``NoOpAffectiveBaselineCheck`` which always returns
``("stable", 1.0)``. Real LLM-driven affect analysis is forcing-function
deferred to AD-486b — needs a corpus of recorded observations from a
real Phase α cohort before it can be calibrated.

Design intent (Sacks 1973 "Awakenings" — phase-gate affective check):
the analyzer asks whether the agent's output tone is stable between
phases. Pulse's self-diagnosed "racing thoughts" was the ProbOS analog
of L-DOPA patients waking up euphoric and crashing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from probos.holodeck.phases import HolodeckPhase


@dataclass(frozen=True)
class AffectiveObservation:
    """Result of an affective baseline check between two phases."""

    status: str  # "stable" | "elevated" | "unstable"
    score: float  # 0.0 (unstable) -> 1.0 (stable)
    note: str = ""


@runtime_checkable
class AffectiveBaselineCheck(Protocol):
    """Narrow Protocol for between-phase affect observation."""

    async def observe(
        self,
        *,
        agent_id: str,
        prev_phase: HolodeckPhase,
        new_phase: HolodeckPhase,
    ) -> AffectiveObservation: ...


class NoOpAffectiveBaselineCheck:
    """v1 implementation. Always returns ``("stable", 1.0)``.

    Replaced by AD-486b LLM-driven analyzer. Forcing function: a Phase α
    cohort has run under ``HolodeckBirthChamberConfig.enabled=True`` and
    affective_observations records exist to validate against.
    """

    async def observe(
        self,
        *,
        agent_id: str,
        prev_phase: HolodeckPhase,
        new_phase: HolodeckPhase,
    ) -> AffectiveObservation:
        return AffectiveObservation(
            status="stable",
            score=1.0,
            note=f"NoOp: {prev_phase.value} -> {new_phase.value}",
        )
```

**`src/probos/holodeck/scheduler.py`** (~110 lines):

```python
"""AD-486: Sequential department activation scheduler.

Per the AD spec at docs/development/roadmap.md:4130, departments are
activated sequentially with observation windows: Security/Operations
first (rapid-assessment trait profile), then Engineering/Science, then
Medical last (thoroughness/perfectionism causes longer calibration).

Observation criterion (NOT a timer): the next department-group is
admitted when every admitted agent in the previous group has reached
HolodeckPhase.SELF_DISCOVERY or higher. This anchors the gate to
completion criteria per the AD-486 spec invariant.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Callable

from probos.holodeck.phases import HolodeckPhase, PHASE_ORDER

logger = logging.getLogger(__name__)


class DepartmentActivationScheduler:
    """Tracks department-grouped admission queue + sequential activation."""

    def __init__(
        self,
        department_order: list[str],
        get_phase_fn: Callable[[str], HolodeckPhase | None],
    ) -> None:
        # Lowercased department names. Empty list = first-come-first-served.
        self._department_order: tuple[str, ...] = tuple(
            d.lower() for d in department_order
        )
        self._get_phase_fn = get_phase_fn
        # Insertion-ordered: agent_id -> (agent_type, department_lc)
        self._queue: "OrderedDict[str, tuple[str, str]]" = OrderedDict()
        self._admitted: set[str] = set()
        self._graduated: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_admission(
        self, agent_id: str, agent_type: str, department: str
    ) -> int:
        """Add an agent to the queue. Returns 1-based queue position."""
        dept_lc = (department or "").lower()
        self._queue[agent_id] = (agent_type, dept_lc)
        return len(self._queue)

    def next_admit_candidate(self) -> str | None:
        """Return the next eligible agent id, or None if blocked.

        v1 algorithm: walk department_order; for each department, if any
        queued non-admitted agent is in that department AND every
        already-admitted agent in earlier departments has reached
        SELF_DISCOVERY or higher, return the next queued agent.
        """
        if not self._department_order:
            for agent_id, _ in self._queue.items():
                if agent_id not in self._admitted:
                    return agent_id
            return None

        for dept in self._department_order:
            if not self._previous_groups_eligible(dept):
                return None
            for agent_id, (_atype, agent_dept) in self._queue.items():
                if agent_id in self._admitted:
                    continue
                if agent_dept == dept:
                    return agent_id
        # Fallthrough — anyone whose department is not in department_order
        for agent_id, (_atype, agent_dept) in self._queue.items():
            if agent_id in self._admitted:
                continue
            if agent_dept not in self._department_order:
                return agent_id
        return None

    def mark_admitted(self, agent_id: str) -> None:
        self._admitted.add(agent_id)

    def mark_graduated(self, agent_id: str) -> None:
        self._graduated.add(agent_id)

    def admitted_count(self) -> int:
        return len(self._admitted)

    def graduated_count(self) -> int:
        return len(self._graduated)

    def queue_size(self) -> int:
        return len(self._queue)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _previous_groups_eligible(self, current_dept: str) -> bool:
        """All earlier-department admitted agents have reached SELF_DISCOVERY+."""
        try:
            current_idx = self._department_order.index(current_dept)
        except ValueError:
            return True  # not in ordered list -> no precedence block
        if current_idx == 0:
            return True
        earlier = set(self._department_order[:current_idx])
        threshold_idx = PHASE_ORDER.index(HolodeckPhase.SELF_DISCOVERY)
        for agent_id in self._admitted:
            entry = self._queue.get(agent_id)
            if entry is None:
                continue
            _, agent_dept = entry
            if agent_dept not in earlier:
                continue
            phase = self._get_phase_fn(agent_id)
            if phase is None:
                return False
            try:
                phase_idx = PHASE_ORDER.index(phase)
            except ValueError:
                return False
            if phase_idx < threshold_idx:
                return False
        return True
```

**`src/probos/holodeck/gates.py`** (~150 lines):

```python
"""AD-486: Phase-completion gate predicates.

Each gate is async because some predicates (calibration episodic count)
require database round-trips. Gates return ``(passed: bool, reason: str)``;
the chamber emits HOLODECK_PHASE_GATE_PASSED or
HOLODECK_PHASE_GATE_BLOCKED accordingly.

Trait-adaptive calibration pacing (AD-494) lives here: high-conscientiousness
agents (Medical) need longer calibration than low-conscientiousness agents
(Security). The multiplier is read via the callsign registry's
``get_profile(agent_type)`` lookup.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.holodeck.chamber import BirthChamberRecord

logger = logging.getLogger(__name__)


def conscientiousness_multiplier(profile: dict[str, Any] | None) -> float:
    """Map a crew_profile dict to a calibration-min-episodes multiplier.

    AD-494 sea-trial evidence: high-conscientiousness agents (Medical) need
    longer calibration; low-conscientiousness (Security) shorter.
    """
    if not profile:
        return 1.0
    personality = profile.get("personality") if isinstance(profile, dict) else None
    if isinstance(personality, dict):
        c = float(personality.get("conscientiousness", 0.5))
    else:
        c = float(getattr(personality, "conscientiousness", 0.5)) if personality else 0.5
    if c >= 0.7:
        return 2.0
    if c <= 0.3:
        return 0.5
    return 1.0


async def gate_orientation_complete(
    record: "BirthChamberRecord",
    services: dict[str, Any],
) -> tuple[bool, str]:
    flags = record.gates_passed
    required = ("identity_grounded", "code_of_conduct_acknowledged",
                "curriculum_orientation_delivered")
    missing = [f for f in required if not flags.get(f, False)]
    if missing:
        return False, f"awaiting: {', '.join(missing)}"
    return True, "orientation acknowledged"


async def gate_calibration_baseline(
    record: "BirthChamberRecord",
    services: dict[str, Any],
) -> tuple[bool, str]:
    base = int(services.get("calibration_min_episodes", 5))
    profile = None
    callsign_registry = services.get("callsign_registry")
    if callsign_registry is not None:
        try:
            profile = callsign_registry.get_profile(record.agent_type)
        except Exception:
            logger.debug(
                "AD-486: callsign_registry.get_profile failed for %s",
                record.agent_type, exc_info=True,
            )
    multiplier = conscientiousness_multiplier(profile)
    effective = max(1, round(base * multiplier))
    episodic_memory = services.get("episodic_memory")
    if episodic_memory is None:
        return True, "no episodic memory; auto-pass"
    try:
        count = await episodic_memory.count_for_agent(record.agent_id)
    except Exception:
        logger.warning(
            "AD-486: episodic_memory.count_for_agent failed for %s; auto-pass",
            record.agent_id, exc_info=True,
        )
        return True, "episodic count unavailable; auto-pass"
    if count >= effective:
        return True, f"baseline established ({count} >= {effective})"
    return False, f"awaiting baseline ({count} / {effective})"


async def gate_self_discovery(
    record: "BirthChamberRecord",
    services: dict[str, Any],
) -> tuple[bool, str]:
    if record.gates_passed.get("self_distillation_probe_succeeded", False):
        return True, "self-distillation probe completed"
    return False, "awaiting self-distillation probe"


async def gate_ship_records(
    record: "BirthChamberRecord",
    services: dict[str, Any],
) -> tuple[bool, str]:
    if not record.gates_passed.get("ship_records_acknowledged", False):
        return False, "awaiting ship records acknowledgment"
    cb = services.get("circuit_breaker")
    if cb is not None:
        try:
            if not cb.should_allow_think(record.agent_id):
                return False, "circuit breaker open; deferring"
        except Exception:
            logger.debug(
                "AD-486: circuit_breaker.should_allow_think failed; ignoring",
                exc_info=True,
            )
    return True, "ship records acknowledged"


async def gate_ward_room_integration(
    record: "BirthChamberRecord",
    services: dict[str, Any],
) -> tuple[bool, str]:
    if record.gates_passed.get("integration_ready", False):
        return True, "integration ready"
    return False, "awaiting integration ready"
```

**`src/probos/holodeck/chamber.py`** (~340 lines). Provided in full:

```python
"""AD-486 v1: Birth Chamber orchestrator.

Public API:
- ``admit(agent)`` after naming ceremony.
- ``try_advance(agent_id)`` checks current-phase gate; advances on pass.
- ``is_graduated(agent_id)`` — production gates short-circuit on this.
- ``acknowledge_*`` setters: orientation steps, ship records, integration.

Late-bind dependencies via public setters per Wave 5 convention #5.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from probos.events import EventType
from probos.holodeck.affect import (
    AffectiveBaselineCheck,
    AffectiveObservation,
    NoOpAffectiveBaselineCheck,
)
from probos.holodeck.gates import (
    gate_calibration_baseline,
    gate_orientation_complete,
    gate_self_discovery,
    gate_ship_records,
    gate_ward_room_integration,
)
from probos.holodeck.phases import HolodeckPhase, next_phase

logger = logging.getLogger(__name__)


@dataclass
class BirthChamberRecord:
    """Per-agent chamber state."""

    agent_id: str
    agent_type: str
    department: str
    current_phase: HolodeckPhase = HolodeckPhase.ORIENTATION
    admitted_at: float = field(default_factory=time.time)
    phase_history: list[tuple[str, float]] = field(default_factory=list)
    gates_passed: dict[str, bool] = field(default_factory=dict)
    affective_observations: list[tuple[str, str, float]] = field(default_factory=list)
    self_discovery_attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "department": self.department,
            "current_phase": self.current_phase.value,
            "admitted_at": self.admitted_at,
            "phase_history": list(self.phase_history),
            "gates_passed": dict(self.gates_passed),
            "affective_observations": list(self.affective_observations),
        }


_GATE_BY_PHASE: dict[HolodeckPhase, Callable[..., Awaitable[tuple[bool, str]]]] = {
    HolodeckPhase.ORIENTATION: gate_orientation_complete,
    HolodeckPhase.CALIBRATION: gate_calibration_baseline,
    HolodeckPhase.SELF_DISCOVERY: gate_self_discovery,
    HolodeckPhase.SHIP_RECORDS: gate_ship_records,
    HolodeckPhase.WARD_ROOM_INTEGRATION: gate_ward_room_integration,
}


class BirthChamber:
    """v1 Birth Chamber orchestrator. AD-486."""

    def __init__(
        self,
        config: Any,
        emit_event_fn: Callable[..., None] | None = None,
        affective_check: AffectiveBaselineCheck | None = None,
    ) -> None:
        self._config = config
        self._emit_event_fn = emit_event_fn
        self._affective_check: AffectiveBaselineCheck = (
            affective_check or NoOpAffectiveBaselineCheck()
        )
        self._records: dict[str, BirthChamberRecord] = {}
        # Late-bound services — public setters per Wave 5 convention #5
        self._personal_ontology_prober: Any = None
        self._curriculum_registry: Any = None
        self._circuit_breaker: Any = None
        self._callsign_registry: Any = None
        self._episodic_memory: Any = None
        # Pending Ward Room subscriptions deferred until graduation
        self._pending_subscriptions: dict[str, list[tuple[str, Callable[..., Awaitable[Any]]]]] = {}
        # Background advance loop task ref (Wave 5 convention #14)
        self._advance_task: asyncio.Task | None = None

    # Public setters
    def set_personal_ontology_prober(self, prober: Any) -> None:
        self._personal_ontology_prober = prober

    def set_curriculum_registry(self, registry: Any) -> None:
        self._curriculum_registry = registry

    def set_circuit_breaker(self, breaker: Any) -> None:
        self._circuit_breaker = breaker

    def set_callsign_registry(self, registry: Any) -> None:
        self._callsign_registry = registry

    def set_episodic_memory(self, memory: Any) -> None:
        self._episodic_memory = memory

    # Records access
    def get_record(self, agent_id: str) -> BirthChamberRecord | None:
        return self._records.get(agent_id)

    def all_records(self) -> tuple[BirthChamberRecord, ...]:
        return tuple(self._records.values())

    def is_admitted(self, agent_id: str) -> bool:
        return agent_id in self._records

    def is_graduated(self, agent_id: str) -> bool:
        rec = self._records.get(agent_id)
        if rec is None:
            return True  # never admitted -> not gated
        return rec.current_phase == HolodeckPhase.GRADUATED

    def get_current_phase(self, agent_id: str) -> HolodeckPhase | None:
        rec = self._records.get(agent_id)
        return rec.current_phase if rec else None

    def queue_pending_subscription(
        self,
        agent_id: str,
        channel_id: str,
        subscribe_fn: Callable[..., Awaitable[Any]],
    ) -> None:
        """Defer a Ward Room subscription until graduation."""
        self._pending_subscriptions.setdefault(agent_id, []).append(
            (channel_id, subscribe_fn)
        )

    # Lifecycle
    async def admit(self, agent: Any, department: str = "") -> BirthChamberRecord:
        rec = BirthChamberRecord(
            agent_id=agent.id,
            agent_type=getattr(agent, "agent_type", ""),
            department=(department or "").lower(),
        )
        rec.phase_history.append((HolodeckPhase.ORIENTATION.value, rec.admitted_at))
        self._records[agent.id] = rec
        self._emit(EventType.HOLODECK_AGENT_ADMITTED, {
            "agent_id": agent.id,
            "agent_type": rec.agent_type,
            "department": rec.department,
        })
        self._emit(EventType.HOLODECK_PHASE_ENTERED, {
            "agent_id": agent.id,
            "phase": HolodeckPhase.ORIENTATION.value,
        })
        # Phase 1 onboarding side-effects: deliver code-of-conduct + curriculum
        await self._deliver_orientation_content(rec)
        return rec

    def acknowledge_orientation_step(self, agent_id: str, step: str) -> None:
        rec = self._records.get(agent_id)
        if rec is None:
            return
        rec.gates_passed[step] = True

    def acknowledge_ship_records(self, agent_id: str) -> None:
        rec = self._records.get(agent_id)
        if rec is not None:
            rec.gates_passed["ship_records_acknowledged"] = True

    def acknowledge_integration_ready(self, agent_id: str) -> None:
        rec = self._records.get(agent_id)
        if rec is not None:
            rec.gates_passed["integration_ready"] = True

    async def try_advance(self, agent_id: str) -> HolodeckPhase:
        rec = self._records.get(agent_id)
        if rec is None:
            return HolodeckPhase.GRADUATED
        if rec.current_phase == HolodeckPhase.GRADUATED:
            return rec.current_phase
        # SELF_DISCOVERY auto-runs probe before checking gate
        if rec.current_phase == HolodeckPhase.SELF_DISCOVERY:
            await self._run_self_discovery_step(rec)
        gate = _GATE_BY_PHASE.get(rec.current_phase)
        if gate is None:
            return rec.current_phase
        services = self._services_dict()
        try:
            passed, reason = await gate(rec, services)
        except Exception:
            logger.warning(
                "AD-486: gate %s raised for agent %s; treating as blocked",
                rec.current_phase.value, rec.agent_id, exc_info=True,
            )
            return rec.current_phase
        if not passed:
            self._emit(EventType.HOLODECK_PHASE_GATE_BLOCKED, {
                "agent_id": rec.agent_id,
                "phase": rec.current_phase.value,
                "reason": reason,
            })
            return rec.current_phase
        prev = rec.current_phase
        new = next_phase(prev)
        rec.current_phase = new
        rec.phase_history.append((new.value, time.time()))
        self._emit(EventType.HOLODECK_PHASE_GATE_PASSED, {
            "agent_id": rec.agent_id,
            "phase": prev.value,
            "next_phase": new.value,
            "reason": reason,
        })
        self._emit(EventType.HOLODECK_PHASE_ENTERED, {
            "agent_id": rec.agent_id,
            "phase": new.value,
        })
        # Affective check between phases
        if getattr(self._config, "affective_baseline_check_enabled", True):
            try:
                obs: AffectiveObservation = await self._affective_check.observe(
                    agent_id=rec.agent_id, prev_phase=prev, new_phase=new,
                )
                rec.affective_observations.append((new.value, obs.status, obs.score))
                self._emit(EventType.HOLODECK_AFFECTIVE_BASELINE_OBSERVED, {
                    "agent_id": rec.agent_id,
                    "phase": new.value,
                    "status": obs.status,
                    "score": obs.score,
                })
            except Exception:
                logger.debug(
                    "AD-486: affective check failed for %s", rec.agent_id, exc_info=True,
                )
        if new == HolodeckPhase.GRADUATED:
            await self._on_graduation(rec)
        return new

    async def run_advance_loop(self) -> None:
        """Background poll. AD-486 v1.

        Iterates all admitted, non-graduated records and calls
        ``try_advance``. Sleeps for ``auto_advance_poll_interval_seconds``.
        Cancellation: re-raises ``asyncio.CancelledError`` per
        copilot-instructions.md async discipline.
        """
        interval = float(getattr(self._config, "auto_advance_poll_interval_seconds", 2.0))
        while True:
            try:
                for agent_id in list(self._records.keys()):
                    rec = self._records.get(agent_id)
                    if rec is None or rec.current_phase == HolodeckPhase.GRADUATED:
                        continue
                    try:
                        await self.try_advance(agent_id)
                    except Exception:
                        logger.warning(
                            "AD-486: try_advance raised for %s; continuing loop",
                            agent_id, exc_info=True,
                        )
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.debug("AD-486: birth chamber advance loop cancelled")
                raise
            except Exception:
                logger.exception("AD-486: advance loop iteration failed")
                await asyncio.sleep(interval)

    # Internal helpers
    async def _deliver_orientation_content(self, rec: BirthChamberRecord) -> None:
        # AD-489 Code of Conduct presentation (text already in cognitive_agent
        # system prompt — chamber emits an event so HXI / observability can
        # tag this as the canonical "code of conduct presented" moment).
        rec.gates_passed["code_of_conduct_acknowledged"] = True
        rec.gates_passed["identity_grounded"] = True
        # AD-507 curriculum: list_by_phase("orientation")
        if self._curriculum_registry is not None:
            try:
                modules = self._curriculum_registry.list_by_phase("orientation")
                module_ids = [getattr(m, "id", "") for m in modules]
                rec.gates_passed["curriculum_orientation_delivered"] = True
                self._emit(EventType.HOLODECK_PHASE_ENTERED, {
                    "agent_id": rec.agent_id,
                    "phase": HolodeckPhase.ORIENTATION.value,
                    "modules": module_ids,
                })
            except Exception:
                logger.warning(
                    "AD-486: curriculum.list_by_phase failed for %s; auto-marking delivered",
                    rec.agent_id, exc_info=True,
                )
                rec.gates_passed["curriculum_orientation_delivered"] = True
        else:
            rec.gates_passed["curriculum_orientation_delivered"] = True

    async def _run_self_discovery_step(self, rec: BirthChamberRecord) -> None:
        if rec.gates_passed.get("self_distillation_probe_succeeded", False):
            return
        prober = self._personal_ontology_prober
        if prober is None:
            rec.gates_passed["self_distillation_probe_succeeded"] = True
            return
        max_attempts = int(getattr(self._config, "max_self_discovery_probe_attempts", 3))
        if rec.self_discovery_attempts >= max_attempts:
            return
        rec.self_discovery_attempts += 1
        domain = "self-knowledge baseline"
        try:
            result = await prober.probe_domain(rec.agent_id, domain)
        except Exception:
            logger.warning(
                "AD-486: probe_domain failed for %s (attempt %d/%d)",
                rec.agent_id, rec.self_discovery_attempts, max_attempts,
                exc_info=True,
            )
            return
        sub_topics = getattr(result, "sub_topics", ())
        if sub_topics:
            rec.gates_passed["self_distillation_probe_succeeded"] = True

    async def _on_graduation(self, rec: BirthChamberRecord) -> None:
        self._emit(EventType.HOLODECK_GRADUATION, {
            "agent_id": rec.agent_id,
            "agent_type": rec.agent_type,
            "department": rec.department,
            "phase_history": list(rec.phase_history),
        })
        # Drain pending Ward Room subscriptions
        pending = self._pending_subscriptions.pop(rec.agent_id, [])
        for channel_id, fn in pending:
            try:
                await fn()
            except Exception:
                logger.warning(
                    "AD-486: pending subscription drain failed for %s/%s",
                    rec.agent_id, channel_id, exc_info=True,
                )

    def _services_dict(self) -> dict[str, Any]:
        return {
            "calibration_min_episodes": int(
                getattr(self._config, "calibration_min_episodes", 5)
            ),
            "callsign_registry": self._callsign_registry,
            "episodic_memory": self._episodic_memory,
            "circuit_breaker": self._circuit_breaker,
        }

    def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        if self._emit_event_fn is None:
            return
        try:
            self._emit_event_fn(event_type, payload)
        except Exception:
            logger.debug(
                "AD-486: emit_event failed for %s", event_type, exc_info=True,
            )
```

### Section 3 — Finalize wirer

`src/probos/startup/finalize.py`. Add `_wire_birth_chamber` adjacent to `_wire_boot_camp_tracker` at verified anchor `:141`. Invoke from the existing finalize chain at `:1457` (after `_wire_boot_camp_tracker`).

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


def _wire_birth_chamber(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-486 v1: Wire Holodeck Birth Chamber + Department scheduler.

    Default-False per AD-695 transitional-flag precedent. When disabled,
    no chamber is constructed; production graduation gates short-circuit
    to ``True`` via the ``runtime.birth_chamber is None`` check.
    """
    cfg = getattr(config, "holodeck_birth_chamber", None)
    if not cfg or not cfg.enabled:
        return False

    import asyncio as _asyncio

    from probos.holodeck import BirthChamber, DepartmentActivationScheduler

    emit_fn = getattr(runtime, "emit_event", None)
    chamber = BirthChamber(config=cfg, emit_event_fn=emit_fn)
    chamber.set_personal_ontology_prober(
        getattr(runtime, "personal_ontology_prober", None)
    )
    chamber.set_curriculum_registry(
        getattr(runtime, "curriculum_registry", None)
    )
    # AD-488 circuit_breaker is a leading-underscore attr on
    # ProactiveCognitiveLoop (predates Wave 5 convention #1). Demeter
    # exception documented; promote to public in a later wave.
    proactive = getattr(runtime, "proactive_loop", None)
    if proactive is not None:
        chamber.set_circuit_breaker(getattr(proactive, "_circuit_breaker", None))
    chamber.set_callsign_registry(getattr(runtime, "callsign_registry", None))
    chamber.set_episodic_memory(getattr(runtime, "episodic_memory", None))

    runtime.birth_chamber = chamber  # public attribute (Wave 5 convention #1)

    scheduler = DepartmentActivationScheduler(
        department_order=list(cfg.department_order),
        get_phase_fn=chamber.get_current_phase,
    )
    runtime.department_activation_scheduler = scheduler  # public attribute

    # Late-bind onto onboarding service so wire_agent can admit agents
    if getattr(runtime, "onboarding", None) is not None:
        try:
            runtime.onboarding.set_birth_chamber(chamber)
        except AttributeError:
            logger.warning(
                "AD-486: onboarding.set_birth_chamber not available; chamber will not auto-admit"
            )

    if cfg.auto_advance_enabled:
        try:
            runtime.birth_chamber_advance_task = _asyncio.create_task(
                chamber.run_advance_loop()
            )
        except RuntimeError:
            # No running loop yet (cold-start before serve()) — finalize
            # is invoked from an async context in normal boot, so this
            # branch is defensive only.
            logger.warning(
                "AD-486: no running event loop; advance task not started"
            )
            runtime.birth_chamber_advance_task = None
    else:
        runtime.birth_chamber_advance_task = None

    logger.info(
        "AD-486: Birth Chamber initialized (auto_advance=%s, departments=%s)",
        cfg.auto_advance_enabled, list(cfg.department_order),
    )
    return True
===END REPLACE===
```

```text
===MODIFY: src/probos/startup/finalize.py===
===SEARCH===
    if _wire_boot_camp_tracker(runtime=runtime, config=config):
        logger.info("AD-509: Boot Camp Phase Tracker v1 wired during finalization")

    if _wire_discovery_learning(runtime=runtime, config=config):
===REPLACE===
    if _wire_boot_camp_tracker(runtime=runtime, config=config):
        logger.info("AD-509: Boot Camp Phase Tracker v1 wired during finalization")

    if _wire_birth_chamber(runtime=runtime, config=config):
        logger.info("AD-486: Holodeck Birth Chamber v1 wired during finalization")

    if _wire_discovery_learning(runtime=runtime, config=config):
===END REPLACE===
```

> **Builder note**: the SEARCH on the second block above is anchored on the verified existing pair of wirer-invocation + logger.info lines at `finalize.py:1457-1461`. The REPLACE inserts the new wirer + matching logger.info between the AD-509 and AD-512 wiring steps so AD-486 sees `personal_ontology_prober` (AD-487) + `curriculum_registry` (AD-507) + `boot_camp_tracker` (AD-509) all already on the runtime when its wirer runs.

### Section 4 — Onboarding service hook

`src/probos/agent_onboarding.py`. Add `_birth_chamber` slot + public setter + admission hook.

```text
===MODIFY: src/probos/agent_onboarding.py===
===SEARCH===
        # AD-628e: TRAINO mentor announcer (post-naming-ceremony hook)
        self._mentor_announcer: Callable[[str, str], Any] | None = None

    def register_mentor_announcer(
===REPLACE===
        # AD-628e: TRAINO mentor announcer (post-naming-ceremony hook)
        self._mentor_announcer: Callable[[str, str], Any] | None = None
        # AD-486: Birth Chamber (late-bound by finalize._wire_birth_chamber)
        self._birth_chamber: Any = None

    def set_birth_chamber(self, chamber: Any) -> None:
        """AD-486: Set the Birth Chamber (public setter for LoD)."""
        self._birth_chamber = chamber

    def register_mentor_announcer(
===END REPLACE===
```

```text
===MODIFY: src/probos/agent_onboarding.py===
===SEARCH===
        # AD-567g: Cognitive re-localization — set orientation context after naming
        if is_crew and self._orientation_service and self._config.orientation.enabled:
===REPLACE===
        # AD-486: Birth Chamber admission (post-naming, pre-orientation-context).
        # Tier-2 log-and-degrade — chamber failures must not block onboarding.
        if (
            is_crew
            and self._birth_chamber is not None
            and self._config.holodeck_birth_chamber.enabled
            and not (
                self._config.holodeck_birth_chamber.bypass_for_existing_agents
                and _existing_identity_callsign
            )
        ):
            try:
                department = ""
                if self._ontology is not None:
                    try:
                        department = (
                            self._ontology.get_agent_department(agent.agent_type) or ""
                        )
                    except Exception:
                        department = ""
                await self._birth_chamber.admit(agent, department=department)
            except Exception:
                logger.warning(
                    "AD-486: birth_chamber.admit failed for %s; continuing without chamber",
                    agent.agent_type, exc_info=True,
                )

        # AD-567g: Cognitive re-localization — set orientation context after naming
        if is_crew and self._orientation_service and self._config.orientation.enabled:
===END REPLACE===
```

### Section 5 — Production graduation gates

**`src/probos/proactive.py`** — gate inside `_run_cycle`. Verified anchor: lines 498-518 around the `eligible_agents` accumulation loop.

```text
===MODIFY: src/probos/proactive.py===
===SEARCH===
        # AD-636: Count eligible agents for stagger calculation
        eligible_agents: list[Any] = []
        for agent in rt.registry.all():
            if not is_crew_agent(agent, rt.ontology):
                continue
            if not agent.is_alive:
                continue
            eligible_agents.append(agent)
===REPLACE===
        # AD-636: Count eligible agents for stagger calculation
        eligible_agents: list[Any] = []
        for agent in rt.registry.all():
            if not is_crew_agent(agent, rt.ontology):
                continue
            if not agent.is_alive:
                continue
            # AD-486: Skip agents still in Birth Chamber (pre-graduation).
            # Default-disabled chamber (no runtime.birth_chamber) treats
            # all agents as graduated → zero behavior change.
            chamber = getattr(rt, "birth_chamber", None)
            if chamber is not None and not chamber.is_graduated(agent.id):
                continue
            eligible_agents.append(agent)
===END REPLACE===
```

**`src/probos/assignment.py`** — defer Ward Room subscription at the two existing call sites. Verified anchors at `:184` (assignment-creation member subscription) and `:310` (add-member subscription). To avoid threading `runtime` through `AssignmentService`, add a public `set_birth_chamber` setter (Wave 5 convention #5) and store the chamber on `self._birth_chamber: Any = None`. The finalize wirer calls `runtime.assignment_service.set_birth_chamber(chamber)` after creating the chamber.

First, add the slot + setter at the AssignmentService constructor / public-API surface. Verify the Builder finds the `__init__` then add adjacent to existing service slots:

```text
===MODIFY: src/probos/assignment.py===
===SEARCH===
        self._emit_event = emit_event
        self._ward_room = ward_room  # WardRoomService reference for auto-channel creation
        self._snapshot_cache: list[dict[str, Any]] = []  # Sync cache for build_state_snapshot
===REPLACE===
        self._emit_event = emit_event
        self._ward_room = ward_room  # WardRoomService reference for auto-channel creation
        # AD-486: Late-bound by finalize._wire_birth_chamber (Wave 5 convention #5)
        self._birth_chamber: Any = None
        self._snapshot_cache: list[dict[str, Any]] = []  # Sync cache for build_state_snapshot
===END REPLACE===
```

Then add the public setter near other public-API methods on the class. The exact insertion site is left to the Builder; insert near other public setters or just below `__init__`. Suggested insertion (Builder may adjust for nearest existing setter):

```python
    def set_birth_chamber(self, chamber: Any) -> None:
        """AD-486: Set the Birth Chamber for Ward Room subscription gating."""
        self._birth_chamber = chamber
```

> **Builder verify-step before applying**: confirm `Any` is already imported in `assignment.py` (the `_snapshot_cache: list[dict[str, Any]]` line above proves it is). The setter is a new public method so no SEARCH/REPLACE is needed for it — the Builder appends it as a new method block on the class.

Site A — assignment-creation flow (currently `:177-185`):

```text
===MODIFY: src/probos/assignment.py===
===SEARCH===
                # Subscribe all members
                for agent_id in members:
                    await self._ward_room.subscribe(agent_id, ch.id)
            except Exception as e:
                logger.debug("Ward Room channel creation failed for assignment: %s", e)
===REPLACE===
                # Subscribe all members
                for agent_id in members:
                    # AD-486: Defer subscription if agent is still in Birth Chamber.
                    if (
                        self._birth_chamber is not None
                        and not self._birth_chamber.is_graduated(agent_id)
                    ):
                        self._birth_chamber.queue_pending_subscription(
                            agent_id, ch.id,
                            (lambda aid=agent_id, cid=ch.id:
                                self._ward_room.subscribe(aid, cid)),
                        )
                    else:
                        await self._ward_room.subscribe(agent_id, ch.id)
            except Exception as e:
                logger.debug("Ward Room channel creation failed for assignment: %s", e)
===END REPLACE===
```

Site B — add-member flow (currently `:303-311`):

```text
===MODIFY: src/probos/assignment.py===
===SEARCH===
        # Subscribe to Ward Room channel if available
        if self._ward_room and assignment.ward_room_channel_id:
            try:
                await self._ward_room.subscribe(agent_id, assignment.ward_room_channel_id)
            except Exception as e:
                logger.debug("Ward Room subscribe failed: %s", e)
===REPLACE===
        # Subscribe to Ward Room channel if available
        if self._ward_room and assignment.ward_room_channel_id:
            try:
                # AD-486: Defer subscription if agent is still in Birth Chamber.
                if (
                    self._birth_chamber is not None
                    and not self._birth_chamber.is_graduated(agent_id)
                ):
                    self._birth_chamber.queue_pending_subscription(
                        agent_id, assignment.ward_room_channel_id,
                        (lambda aid=agent_id, cid=assignment.ward_room_channel_id:
                            self._ward_room.subscribe(aid, cid)),
                    )
                else:
                    await self._ward_room.subscribe(agent_id, assignment.ward_room_channel_id)
            except Exception as e:
                logger.debug("Ward Room subscribe failed: %s", e)
===END REPLACE===
```

And update the finalize wirer Section 3 to call `assignment_service.set_birth_chamber(chamber)`. Add this line inside `_wire_birth_chamber` after the `runtime.birth_chamber = chamber` assignment:

```python
    # AD-486: Late-bind onto AssignmentService for Ward Room subscription gating
    _assn = getattr(runtime, "assignment_service", None)
    if _assn is not None:
        try:
            _assn.set_birth_chamber(chamber)
        except AttributeError:
            logger.warning(
                "AD-486: assignment_service.set_birth_chamber not available; "
                "Ward Room subscription will not be deferred"
            )
```

(Builder folds this into the Section 3 wirer body alongside the existing `runtime.onboarding.set_birth_chamber(chamber)` call.)

## 4. Tests — `tests/test_ad486_birth_chamber.py`

50 focused tests across 8 classes. Use real `SystemConfig()` instances with `holodeck_birth_chamber=HolodeckBirthChamberConfig(enabled=True)` overrides; no `Config()` fallback branches per architect anti-pattern list.

### Class A — `HolodeckPhase` enum (5 tests)
1. `test_phase_values` — exact string values for all 6 phases.
2. `test_phase_order_length` — `PHASE_ORDER` length is 6.
3. `test_next_phase_orientation_to_calibration`.
4. `test_next_phase_ward_room_to_graduated`.
5. `test_next_phase_graduated_returns_graduated`.

### Class B — `HolodeckBirthChamberConfig` (4 tests)
6. `test_config_defaults` — `enabled=False`, `bypass_for_existing_agents=True`, default department order.
7. `test_config_calibration_min_episodes_validator_rejects_zero`.
8. `test_config_department_order_lowercased`.
9. `test_config_max_probe_attempts_rejects_zero`.

### Class C — `BirthChamberRecord` (3 tests)
10. `test_record_initial_state` — `current_phase == ORIENTATION`, empty history/observations/gates.
11. `test_record_to_dict_round_trip` — dict shape + types.
12. `test_record_self_discovery_attempts_default_zero`.

### Class D — Gate predicates (10 tests)
13. `test_gate_orientation_blocks_when_no_flags`.
14. `test_gate_orientation_passes_when_three_flags_set`.
15. `test_gate_calibration_passes_when_episode_count_meets_threshold` — uniform conscientiousness 0.5 → multiplier 1.0.
16. `test_gate_calibration_high_conscientiousness_doubles_threshold` — profile with `conscientiousness=0.8` → 10 episodes required.
17. `test_gate_calibration_low_conscientiousness_halves_threshold`.
18. `test_gate_calibration_no_episodic_memory_auto_passes`.
19. `test_gate_self_discovery_blocks_until_probe_succeeds`.
20. `test_gate_ship_records_blocks_when_circuit_breaker_open`.
21. `test_gate_ship_records_passes_when_acknowledged_and_breaker_closed`.
22. `test_gate_ward_room_integration_passes_only_when_flag_set`.

### Class E — `BirthChamber` orchestrator (12 tests)
23. `test_admit_creates_record_with_orientation_phase`.
24. `test_admit_emits_admitted_and_phase_entered_events` — assert two emit calls.
25. `test_admit_calls_curriculum_list_by_phase_orientation` — `MagicMock` curriculum, assert `list_by_phase("orientation")`.
26. `test_try_advance_orientation_to_calibration` — set the three orientation flags, advance.
27. `test_try_advance_blocks_when_gate_returns_false` — assert `HOLODECK_PHASE_GATE_BLOCKED` emitted with reason.
28. `test_try_advance_emits_phase_gate_passed` — assert payload shape.
29. `test_try_advance_calls_affective_check_between_phases` — capture `AffectiveObservation`.
30. `test_try_advance_self_discovery_runs_probe` — `MagicMock` prober returning `sub_topics=("foo",)`.
31. `test_try_advance_self_discovery_probe_failure_does_not_advance` — prober raises `ProbeRateLimitedError`.
32. `test_try_advance_self_discovery_attempts_capped_at_max` — `max_self_discovery_probe_attempts=2`; third call no-ops.
33. `test_try_advance_graduation_drains_pending_subscriptions` — register 2 pending subs, advance to GRADUATED, assert both fns called.
34. `test_try_advance_graduation_emits_holodeck_graduation_event`.

### Class F — `is_graduated` production-gate semantics (4 tests)
35. `test_is_graduated_returns_true_for_unknown_agent` — never-admitted agents are not gated.
36. `test_is_graduated_returns_false_during_orientation`.
37. `test_is_graduated_returns_true_after_full_walk` — admit + 5 successful advances → True.
38. `test_get_current_phase_none_for_unknown`.

### Class G — `DepartmentActivationScheduler` (7 tests)
39. `test_register_admission_returns_position`.
40. `test_next_candidate_first_in_first_department`.
41. `test_next_candidate_blocks_until_previous_group_reaches_self_discovery` — security agent admitted+at ORIENTATION; engineering candidate exists; `next_admit_candidate()` returns None.
42. `test_next_candidate_unblocks_when_previous_group_at_self_discovery` — security admitted at SELF_DISCOVERY; next returns engineering agent.
43. `test_next_candidate_empty_department_order_is_fcfs`.
44. `test_unknown_department_falls_through_to_default_bucket_after_known_groups`.
45. `test_mark_admitted_excludes_from_future_candidates`.

### Class H — Wirer + onboarding integration (5 tests)
46. `test_wirer_no_op_when_disabled` — `enabled=False` → returns False, `runtime.birth_chamber` not set.
47. `test_wirer_constructs_chamber_and_scheduler_when_enabled` — assert `runtime.birth_chamber is not None`, `runtime.department_activation_scheduler is not None`, `birth_chamber_advance_task` set when `auto_advance_enabled=True`.
48. `test_onboarding_admits_crew_agent_when_chamber_enabled` — patch `wire_agent` flow, assert `chamber.is_admitted(agent.id)` after the call.
49. `test_onboarding_skips_admission_for_warm_boot_when_bypass_true` — preset birth-cert callsign on the agent path, assert `chamber.is_admitted` is False.
50. `test_proactive_loop_skips_pre_graduation_agent` — exercise the `_run_cycle` gate via a stub runtime with one admitted-orientation agent; assert that agent is not in the dispatched set.

## 5. What this AD does NOT change

- **AD-509 `BootCampPhaseTracker`** — left untouched. Different phase enum (orientation/core_knowledge/a_school/calibration/integration), still observational. Two trackers coexist; AD-509 may eventually consume chamber events but that is AD-509b/d/e territory.
- **AD-638 `BootCampCoordinator`** — the cold-start post-reset protocol (`src/probos/boot_camp.py`) stays orthogonal. It uses live Ward Room directly (not Holodeck-isolated). Different problem (refresh / re-bonding) than first-instantiation onboarding.
- **AD-499 self-naming ceremony** — chamber admission happens AFTER naming returns. The ceremony itself is unchanged.
- **AD-628e mentor announcer** — fires post-naming, BEFORE chamber admission. v1 does not relocate the announcer call. The forcing-function deferral AD-628e-2 (re-order announcer to fire post-graduation) is tracked under issue #54 if the re-order is later judged necessary.
- **AD-489 Code of Conduct text** — already in the cognitive_agent system prompt. v1 emits an event tagging the moment but does not duplicate or relocate the text.
- **AD-487 PersonalOntologyProber** — the prober itself is unchanged. v1 only invokes `probe_domain` as a Phase 3 driver.
- **AD-488 CognitiveCircuitBreaker** — unchanged. Phase 4 gate consumes `should_allow_think` read-only.
- **AD-494 PersonalityTraits** — unchanged. The conscientiousness multiplier is read via the existing `CallsignRegistry.get_profile(agent_type)` lookup.
- **No new GH issues minted.** AD-486b and AD-486e are roadmap forward-references with explicit forcing functions, not GH tracking issues. They become issues only if their forcing functions trip.
- **No HXI surface.** v1 emits events; HXI panel for chamber progress is a future wave.
- **No NATS / federation coupling.** Single-instance only; cross-instance cohort analytics is class-extension territory under the private commercial repository (out-of-repo).
- **No commercial-tier overlay content.** The advanced templated onboarding tracks, mentor-assignment workflows beyond AD-628e's announcer hook, and fleet-level cohort dashboards are all class-extension territory under the private commercial repository — descriptor-only references in this prompt.

## 6. Tracking and tracker updates

### `DECISIONS.md` — add a new architectural decision entry

Insert into `decisions-era-4-evolution.md` after the AD-486 status block at the existing line range (search anchor: `Status:` at `decisions-era-4-evolution.md:1168` — the `AD-486, AD-487, AD-488, AD-489 — PLANNED` line). Replace the AD-486 status only (AD-487/488/489 stay as-shipped):

```text
===MODIFY: decisions-era-4-evolution.md===
===SEARCH===
**Status:** AD-486, AD-487, AD-488, AD-489 — PLANNED. Documented 2026-03-27.
===REPLACE===
**Status:** AD-486 v1 SHIPPED Wave 99 (2026-05-07) — `src/probos/holodeck/` package: `BirthChamber` orchestrator (340 LOC), 5-phase `HolodeckPhase` enum, `BirthChamberRecord` dataclass, 5 phase-gate predicates with completion-criteria semantics (NOT timers), `DepartmentActivationScheduler` with sequential Security/Operations → Engineering/Science → Medical activation, `AffectiveBaselineCheck` Protocol + `NoOpAffectiveBaselineCheck` v1 stub, AD-487 PersonalOntologyProber Phase 3 wire, AD-507 CoreKnowledgeCurriculumRegistry Phase 1 wire, AD-488 CognitiveCircuitBreaker Phase 4 gate, AD-494 trait-adaptive calibration multiplier (high-conscientiousness 2x, low 0.5x). Six new EventTypes. New `HolodeckBirthChamberConfig` (default-False per AD-695 transitional-flag precedent). Late-bound `runtime.birth_chamber` + `runtime.department_activation_scheduler` (Wave 5 convention #1). Production gates: proactive-loop dispatch + Ward Room subscription deferred until `is_graduated()` returns True. 50 tests at `tests/test_ad486_birth_chamber.py`. Forcing-function deferrals: AD-486b (LLM-based affective baseline check; needs Phase α corpus), AD-486e (Holodeck construct abstraction; needs second consumer per AD-510). AD-487, AD-488, AD-489 — shipped earlier. Documented 2026-03-27.
===END REPLACE===
```

### `docs/development/roadmap.md` — flip status

```text
===MODIFY: docs/development/roadmap.md===
===SEARCH===
**AD-486: Holodeck Birth Chamber — Graduated Cognitive Onboarding** *(planned, OSS)*
===REPLACE===
**AD-486: Holodeck Birth Chamber — Graduated Cognitive Onboarding** *(v1 shipped Wave 99, OSS — `src/probos/holodeck/` package; 50 focused tests; default-False per AD-695. Forcing-function children: AD-486b LLM-based affective baseline check, AD-486e Holodeck construct abstraction.)*
===END REPLACE===
```

### `PROGRESS.md` — append wave-99 close paragraph at the top of the file

Builder writes the close paragraph after the Wave-78 paragraph at the file head. Format follows the W77/W90/W95/W98 closes (see `PROGRESS.md:1-9`).

### `prompts/wave-plan.yaml` — append entry

```yaml
  - id: "99"
    title: "AD-486 v1 Holodeck Birth Chamber — Graduated Cognitive Onboarding (closes #24)"
    kind: single
    depends_on: ["98"]
    dispatch_prompt: "prompts/WAVE-99-DISPATCH.md"
    prompts_already_drafted: true
    prompt_paths:
      - "prompts/ad-486-holodeck-birth-chamber-v1.md"
    builder_required: true
    issues_to_close: [24]
    status: pending
```

## 7. Acceptance criteria

1. `pytest tests/test_ad486_birth_chamber.py -v -n 0` — 50 tests pass.
2. Full gate `pytest tests/ -q -n 4 --dist=loadfile` — `>= 12260 passed` (baseline 12210 + 50 new). Δ exactly +50 expected.
3. `runtime.birth_chamber is None` when `holodeck_birth_chamber.enabled=False` (default). No proactive-loop or Ward Room behavior change in default config.
4. With `enabled=True`: a fresh crew agent walks ORIENTATION → CALIBRATION → SELF_DISCOVERY → SHIP_RECORDS → WARD_ROOM_INTEGRATION → GRADUATED under the gate predicates. Six new EventTypes are emitted at the right moments.
5. With `enabled=True` and `bypass_for_existing_agents=True` (default): warm-boot agents (existing birth certificate found) skip admission and behave identically to today.
6. `pre-commit` hook runs cleanly (no banned-pattern matches).
7. `gh issue close 24 -c "<canonical Wave 99 close paragraph>"`.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 8. Verified Against Codebase (2026-05-07, HEAD `4bdf23a`)

```
git ls-files src/probos/holodeck/
  (no output — package does not exist; greenfield)

grep -n "def wire_agent" src/probos/agent_onboarding.py
  118:    async def wire_agent(self, agent: Any) -> None:

grep -n "_mentor_announcer" src/probos/agent_onboarding.py
  83:        self._mentor_announcer: Callable[[str, str], Any] | None = None
  96:        self._mentor_announcer = announcer

grep -n "_orientation_service and self._config.orientation.enabled" src/probos/agent_onboarding.py
  277:        if is_crew and self._orientation_service and self._config.orientation.enabled:

grep -n "class OnboardingConfig" src/probos/config.py
  1748:class OnboardingConfig(BaseModel):

grep -n "    onboarding: OnboardingConfig" src/probos/config.py
  2760:    onboarding: OnboardingConfig = OnboardingConfig()

grep -n "^class CoreKnowledgeCurriculumRegistry\|def list_by_phase" src/probos/crew_development/curriculum.py
  154:class CoreKnowledgeCurriculumRegistry:
  186:    def list_by_phase(self, phase: str) -> tuple[CurriculumModule, ...]:

grep -n "class PersonalOntologyProber\|async def probe_domain" src/probos/cognitive/self_distillation/prober.py
  66:class PersonalOntologyProber:
  121:    async def probe_domain(self, agent_id: str, domain: str) -> ProbeResult:

grep -n "should_allow_think" src/probos/cognitive/circuit_breaker.py
  (verified — method exists; AD-488 shipped per docs/development/roadmap.md:4133)

grep -n "class CallsignRegistry\|def get_profile" src/probos/crew_profile.py
  (CallsignRegistry holds profiles; get_profile returns dict per :406)

grep -n "BOOT_CAMP_PHASE_ADVANCED" src/probos/events.py
  385:    BOOT_CAMP_PHASE_ADVANCED = "boot_camp_phase_advanced"  # AD-509

grep -n "_wire_boot_camp_tracker" src/probos/startup/finalize.py
  141:def _wire_boot_camp_tracker(*, runtime: Any, config: "SystemConfig") -> bool:
  1457:    if _wire_boot_camp_tracker(runtime=runtime, config=config):

grep -n "eligible_agents.append" src/probos/proactive.py
  504:            eligible_agents.append(agent)

grep -n "await self._ward_room.subscribe" src/probos/assignment.py
  184:                    await self._ward_room.subscribe(agent_id, ch.id)
  310:                await self._ward_room.subscribe(agent_id, assignment.ward_room_channel_id)

grep -rn "AD-486\|HolodeckBirthChamber\|BirthChamber" src/probos/
  (only docstring/prose mentions in config.py:2670, agent_onboarding.py:614,
   crew_development/discovery/* — no live class or import; greenfield)
```

All claimed symbols exist except those explicitly introduced by this prompt's SEARCH/REPLACE pairs:

- New EventType values (Section 0) — introduced by this prompt.
- `HolodeckBirthChamberConfig` and `SystemConfig.holodeck_birth_chamber` (Section 1) — introduced by this prompt.
- `src/probos/holodeck/` package + `BirthChamber`, `BirthChamberRecord`, `HolodeckPhase`, etc. (Section 2) — introduced by this prompt.
- `_wire_birth_chamber` (Section 3) — introduced by this prompt.
- `AgentOnboardingService.set_birth_chamber` and `_birth_chamber` slot (Section 4) — introduced by this prompt.
- Production gates in `proactive.py:498-518` and `assignment.py:184/310` (Section 5) — modify existing code, anchors verified above.
