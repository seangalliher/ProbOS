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
