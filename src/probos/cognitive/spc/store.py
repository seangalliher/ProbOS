"""AD-522 v1: SPCCalibrationStore — per-agent profile registry and rule runner."""

from __future__ import annotations

import logging
from typing import Any, Callable

from probos.cognitive.spc.calibration_profile import AgentCalibrationProfile
from probos.cognitive.spc.rules import RuleViolation, WesternElectricRules
from probos.events import EventType

logger = logging.getLogger(__name__)


class SPCCalibrationStore:
    """Per-agent SPC profiles. AD-522 v1.

    Stores ``AgentCalibrationProfile`` instances; runs ``WesternElectricRules.check``
    on demand. Emits ``SPC_RULE_VIOLATED`` per detected violation.
    """

    def __init__(self, runtime: Any, *, sample_window: int = 100) -> None:
        self._runtime = runtime
        self._sample_window = sample_window
        self._profiles: dict[str, AgentCalibrationProfile] = {}
        self.emit_event: Callable[..., None] | None = None

    def get_or_create(self, agent_id: str) -> AgentCalibrationProfile:
        prof = self._profiles.get(agent_id)
        if prof is None:
            prof = AgentCalibrationProfile(
                agent_id=agent_id,
                sample_window=self._sample_window,
            )
            self._profiles[agent_id] = prof
        return prof

    def record_observation(self, agent_id: str, value: float) -> None:
        prof = self.get_or_create(agent_id)
        prof.record_observation(value)

    def check_rules(self, agent_id: str, window_size: int = 20) -> list[RuleViolation]:
        prof = self._profiles.get(agent_id)
        if prof is None:
            return []
        violations = WesternElectricRules.check(prof, window_size=window_size)
        for v in violations:
            self._emit_violation(agent_id, v)
        return violations

    def all_profiles(self) -> tuple[AgentCalibrationProfile, ...]:
        return tuple(self._profiles.values())

    def _emit_violation(self, agent_id: str, violation: RuleViolation) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.SPC_RULE_VIOLATED,
                {
                    "agent_id": agent_id,
                    "rule_name": violation.rule_name,
                    "description": violation.description,
                },
            )
        except Exception:
            logger.warning("AD-522: emit_event failed", exc_info=True)
