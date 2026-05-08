"""AD-509b/c/d + AD-507b: Boot camp continuations + curriculum progression tracking.

Foundation cuts of four sibling ADs that compose with AD-507/AD-509 v1:

    * AD-507b — ``CurriculumProgressionTracker`` records per-agent module
      completion. In-memory record store; a future AD persists.
    * AD-509b — ``ASchoolCurriculum`` selects per-department module
      sequences. Pure mapping over the AD-507 catalog.
    * AD-509c — ``GraduatedStimuliMonitor`` tracks cognitive-load proxies
      (working-memory pressure, decision-queue depth) and recommends a
      stimulus level for the agent's current boot-camp phase.
    * AD-509d — ``CompletionCriteriaGate`` evaluates per-phase completion
      criteria so phase advancement can swap from time-based to outcome-
      based gating. Receives a tracker + agent_id and returns a Decision.

All four are read-mostly observation surfaces in v1 — they do not
modify boot-camp state or agent behavior. Wiring into the existing
``BootCampPhaseTracker.advance_phase`` is the forcing function for
AD-509f.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AD-507b — CurriculumProgressionTracker
# ---------------------------------------------------------------------------


@dataclass
class CurriculumProgressionTracker:
    """Per-agent record of completed curriculum modules."""

    _records: dict[str, set[str]] = field(default_factory=dict)

    def mark_completed(self, agent_id: str, module_id: str) -> None:
        if not agent_id or not module_id:
            return
        self._records.setdefault(agent_id, set()).add(module_id)

    def is_completed(self, agent_id: str, module_id: str) -> bool:
        return module_id in self._records.get(agent_id, set())

    def completed_modules(self, agent_id: str) -> tuple[str, ...]:
        return tuple(sorted(self._records.get(agent_id, set())))

    def completion_count(self, agent_id: str) -> int:
        return len(self._records.get(agent_id, set()))

    def reset_agent(self, agent_id: str) -> bool:
        return self._records.pop(agent_id, None) is not None


# ---------------------------------------------------------------------------
# AD-509b — A-School per-department curriculum
# ---------------------------------------------------------------------------


_DEFAULT_DEPARTMENT_TRACKS: dict[str, tuple[str, ...]] = {
    "medical": ("identity_grounding", "communication", "trust_basics", "memory_basics", "ethics_boundaries", "help_seeking"),
    "engineering": ("identity_grounding", "communication", "trust_basics", "self_regulation", "ethics_boundaries"),
    "science": ("identity_grounding", "communication", "memory_basics", "self_regulation", "ethics_boundaries"),
    "security": ("identity_grounding", "trust_basics", "ethics_boundaries", "self_regulation"),
    "operations": ("identity_grounding", "communication", "trust_basics", "self_regulation"),
    "communications": ("identity_grounding", "communication", "trust_basics", "ethics_boundaries"),
    "bridge": ("identity_grounding", "communication", "trust_basics", "ethics_boundaries", "help_seeking"),
}


class ASchoolCurriculum:
    """AD-509b: per-department module sequence."""

    def __init__(self, tracks: dict[str, tuple[str, ...]] | None = None) -> None:
        self._tracks = dict(tracks or _DEFAULT_DEPARTMENT_TRACKS)

    def modules_for(self, department: str) -> tuple[str, ...]:
        return tuple(self._tracks.get((department or "").lower(), ()))

    def departments(self) -> tuple[str, ...]:
        return tuple(sorted(self._tracks.keys()))

    def register_track(self, department: str, modules: tuple[str, ...]) -> None:
        self._tracks[department.lower()] = tuple(modules)

    def next_module_for(
        self,
        department: str,
        progression: CurriculumProgressionTracker,
        agent_id: str,
    ) -> str | None:
        for mod in self.modules_for(department):
            if not progression.is_completed(agent_id, mod):
                return mod
        return None


# ---------------------------------------------------------------------------
# AD-509c — Graduated stimuli monitor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StimuliRecommendation:
    """Per-agent stimulus level recommendation."""

    agent_id: str
    level: str  # 'minimal' | 'limited' | 'department' | 'ship_wide'
    reason: str
    cognitive_load: float


class GraduatedStimuliMonitor:
    """AD-509c: maps (boot-camp phase, cognitive load) -> stimulus level."""

    def __init__(self, *, high_load_threshold: float = 0.75) -> None:
        self._high_load = high_load_threshold

    def recommend(
        self,
        *,
        agent_id: str,
        boot_camp_phase: str,
        cognitive_load: float = 0.0,
    ) -> StimuliRecommendation:
        # Heavy cognitive load always pulls level down regardless of phase.
        if cognitive_load >= self._high_load:
            return StimuliRecommendation(
                agent_id=agent_id,
                level="minimal",
                reason=f"high cognitive load {cognitive_load:.2f}",
                cognitive_load=cognitive_load,
            )
        phase = (boot_camp_phase or "").lower()
        if phase in {"orientation", "core_knowledge"}:
            level = "minimal"
        elif phase == "a_school":
            level = "limited"
        elif phase == "calibration":
            level = "department"
        elif phase in {"integration", "completed"}:
            level = "ship_wide"
        else:
            level = "minimal"
        return StimuliRecommendation(
            agent_id=agent_id,
            level=level,
            reason=f"phase {phase or 'unknown'}",
            cognitive_load=cognitive_load,
        )


# ---------------------------------------------------------------------------
# AD-509d — Completion-criteria gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateDecision:
    advance: bool
    reason: str
    missing: tuple[str, ...] = ()


_PHASE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "orientation": ("identity_grounding",),
    "core_knowledge": ("identity_grounding", "communication", "trust_basics"),
    "a_school": ("identity_grounding", "communication", "trust_basics", "memory_basics"),
    "calibration": ("identity_grounding", "communication", "trust_basics", "memory_basics", "ethics_boundaries"),
    "integration": ("identity_grounding", "communication", "trust_basics", "memory_basics", "ethics_boundaries", "self_regulation"),
}


class CompletionCriteriaGate:
    """AD-509d: gate phase advancement on module-completion criteria."""

    def __init__(
        self,
        *,
        progression: CurriculumProgressionTracker,
        requirements: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._progression = progression
        self._reqs = dict(requirements or _PHASE_REQUIREMENTS)

    def evaluate(self, *, agent_id: str, current_phase: str) -> GateDecision:
        phase = (current_phase or "").lower()
        required = self._reqs.get(phase)
        if not required:
            return GateDecision(advance=True, reason=f"no requirements for phase {phase!r}")
        missing = tuple(
            mod for mod in required
            if not self._progression.is_completed(agent_id, mod)
        )
        if missing:
            return GateDecision(
                advance=False,
                reason=f"{len(missing)} module(s) incomplete",
                missing=missing,
            )
        return GateDecision(advance=True, reason="all requirements satisfied")

    def register_requirements(self, phase: str, modules: tuple[str, ...]) -> None:
        self._reqs[phase.lower()] = tuple(modules)
