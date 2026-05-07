"""AD-628g: LIMDU (Limited Duty) protocol — joint Medical+TRAINO recommendation.

Joint authority enforced at the type level via two required keyword-only
parameters (medical_callsign, traino_callsign). Per-callsign role
validation is a calling-agent-level concern; this module does not enforce
that medical_callsign actually belongs to a Medical agent.

Snapshot model: recommend_limited_duty reads the AD-628b profile at
recommendation time only — there is no live SKILL_EXERCISED subscription
(W93-4 hard-stop: feedback-loop avoidance).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable, Literal

from probos.events import EventType

if TYPE_CHECKING:
    from probos.cognitive.circuit_breaker import CognitiveZone
    from probos.cognitive.drill_calendar import DrillCalendar, DrillEntry
    from probos.cognitive.skill_readiness import AgentSkillReadinessService

logger = logging.getLogger(__name__)


LIMDUStatus = Literal["recommended", "accepted", "completed", "expired"]


@dataclass(frozen=True)
class LIMDURecommendation:
    """AD-628g: a recorded LIMDU recommendation."""

    recommendation_id: str
    agent_id: str
    medical_callsign: str
    traino_callsign: str
    reason: str
    cognitive_zone: Any  # CognitiveZone (avoid circular import for runtime use)
    regressed_skills: list[str] = field(default_factory=list)
    remediation_plan: list["DrillEntry"] = field(default_factory=list)
    created_at: float = 0.0
    status: LIMDUStatus = "recommended"


class LIMDUService:
    """AD-628g: LIMDU recommendation service with auto-populated remediation plan."""

    def __init__(
        self,
        readiness_service: "AgentSkillReadinessService",
        drill_calendar: "DrillCalendar",
        *,
        circuit_breaker: Any | None = None,
        test_for_skill: Callable[[str], str | None] | None = None,
    ) -> None:
        self._readiness = readiness_service
        self._drill_calendar = drill_calendar
        self._circuit_breaker = circuit_breaker
        self._test_for_skill = test_for_skill
        self._recommendations: dict[str, LIMDURecommendation] = {}
        self._next_id = 0
        self._event_emitter: Callable[[Any, dict[str, Any]], None] | None = None

    def set_event_emitter(
        self,
        emitter: "Callable[[Any, dict[str, Any]], None] | None",
    ) -> None:
        """Register an event emitter for LIMDU_RECOMMENDED events."""
        self._event_emitter = emitter

    def _emit(self, event_type: Any, payload: dict[str, Any]) -> None:
        if self._event_emitter is None:
            return
        try:
            self._event_emitter(event_type, payload)
        except Exception:
            logger.warning(
                "AD-628g: LIMDU event emit failed for %s", event_type, exc_info=True,
            )

    def _lookup_qualification_test(self, skill_id: str) -> str | None:
        if self._test_for_skill is None:
            return None
        try:
            return self._test_for_skill(skill_id)
        except Exception:
            return None

    def _resolve_cognitive_zone(self, agent_id: str) -> Any:
        from probos.cognitive.circuit_breaker import CognitiveZone
        if self._circuit_breaker is None:
            return CognitiveZone.GREEN
        try:
            zone = self._circuit_breaker.get_zone(agent_id)
            if isinstance(zone, CognitiveZone):
                return zone
            if isinstance(zone, str):
                try:
                    return CognitiveZone(zone)
                except ValueError:
                    return CognitiveZone.GREEN
            if zone is not None:
                return zone
        except Exception:
            pass
        return CognitiveZone.GREEN

    async def recommend_limited_duty(
        self,
        agent_id: str,
        *,
        medical_callsign: str,
        traino_callsign: str,
        reason: str,
    ) -> LIMDURecommendation:
        """Generate a LIMDU recommendation with auto-populated remediation plan.

        Joint authority enforced at signature level — both medical_callsign
        and traino_callsign are required keyword-only parameters.
        """
        profile = await self._readiness.get_profile(agent_id)
        regressed_skills = [r.skill_id for r in profile.recent_regressions]

        remediation: list["DrillEntry"] = []
        scheduled_at = time.time() + 86400.0
        for skill_id in regressed_skills:
            test_name = self._lookup_qualification_test(skill_id)
            if test_name is None:
                continue
            try:
                drill_id = self._drill_calendar.schedule_drill(
                    agent_id=agent_id,
                    qualification_test=test_name,
                    scheduled_at=scheduled_at,
                )
            except KeyError:
                # Test not registered — skip silently per tier-1 spec
                continue
            entry = self._drill_calendar.get_drill(drill_id)
            if entry is not None:
                remediation.append(entry)

        zone = self._resolve_cognitive_zone(agent_id)

        self._next_id += 1
        recommendation_id = f"limdu-{self._next_id}"
        now = time.time()
        rec = LIMDURecommendation(
            recommendation_id=recommendation_id,
            agent_id=agent_id,
            medical_callsign=medical_callsign,
            traino_callsign=traino_callsign,
            reason=reason,
            cognitive_zone=zone,
            regressed_skills=regressed_skills,
            remediation_plan=remediation,
            created_at=now,
            status="recommended",
        )
        self._recommendations[recommendation_id] = rec

        self._emit(EventType.LIMDU_RECOMMENDED, {
            "recommendation_id": recommendation_id,
            "agent_id": agent_id,
            "medical_callsign": medical_callsign,
            "traino_callsign": traino_callsign,
            "reason": reason,
            "cognitive_zone": getattr(zone, "value", str(zone)),
            "regressed_skills": list(regressed_skills),
            "drill_count": len(remediation),
            "timestamp": now,
        })
        return rec

    def get_recommendation(self, recommendation_id: str) -> LIMDURecommendation | None:
        return self._recommendations.get(recommendation_id)

    def list_active_recommendations(self) -> list[LIMDURecommendation]:
        return [
            r for r in self._recommendations.values()
            if r.status not in ("completed", "expired")
        ]

    def update_status(
        self, recommendation_id: str, status: str,
    ) -> LIMDURecommendation | None:
        existing = self._recommendations.get(recommendation_id)
        if existing is None:
            return None
        if status not in ("recommended", "accepted", "completed", "expired"):
            raise ValueError(f"AD-628g: invalid LIMDU status {status!r}")
        updated = replace(existing, status=status)  # type: ignore[arg-type]
        self._recommendations[recommendation_id] = updated
        return updated
