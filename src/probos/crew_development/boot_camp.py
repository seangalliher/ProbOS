"""Boot Camp Phase Tracker (AD-509 v1).

Per-agent in-memory phase progression record. Read-only observational;
no actual phase gating, no Holodeck integration.

v1 ships ``BootCampPhaseTracker`` only. A-School per-department curriculum
(AD-509b), graduated stimuli (AD-509c), completion-criteria gating
(AD-509d), and trait-adaptive pacing (AD-509e) are deferred.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


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
    phase_history: list[tuple[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "current_phase": self.current_phase.value,
            "started_at": self.started_at,
            "phase_history": list(self.phase_history),
        }


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
            rec.phase_history.append(
                (BootCampPhase.ORIENTATION.value, rec.started_at)
            )
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

    def _emit(
        self,
        agent_id: str,
        prev: BootCampPhase,
        new: BootCampPhase,
    ) -> None:
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
            logger.warning(
                "AD-509: emit_event failed for agent_id=%s; continuing without event",
                agent_id,
                exc_info=True,
            )
