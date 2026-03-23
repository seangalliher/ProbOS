"""CounselorAgent — cognitive wellness monitoring for the crew (AD-378).

Bridge-level CognitiveAgent. Monitors cognitive health, maintains psychological
profiles, detects drift from baseline, advises the Captain on crew wellness
and promotion fitness.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import IntentDescriptor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cognitive Profile — the Counselor's assessment record per agent
# ---------------------------------------------------------------------------

@dataclass
class CognitiveBaseline:
    """Snapshot of an agent's cognitive metrics at time of baselining."""
    trust_score: float = 0.5
    confidence: float = 0.8
    hebbian_avg: float = 0.0
    success_rate: float = 0.0
    captured_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trust_score": self.trust_score,
            "confidence": self.confidence,
            "hebbian_avg": self.hebbian_avg,
            "success_rate": self.success_rate,
            "captured_at": self.captured_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CognitiveBaseline":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CounselorAssessment:
    """A timestamped cognitive assessment — the Counselor's professional opinion."""
    timestamp: float = 0.0
    agent_id: str = ""
    # Current metrics at time of assessment
    trust_score: float = 0.0
    confidence: float = 0.0
    hebbian_avg: float = 0.0
    success_rate: float = 0.0
    personality_drift: float = 0.0
    # Computed drift from baseline
    trust_drift: float = 0.0        # current - baseline
    confidence_drift: float = 0.0
    hebbian_drift: float = 0.0
    # Counselor's assessment
    wellness_score: float = 1.0     # 0.0 = critical, 1.0 = excellent
    concerns: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    fit_for_duty: bool = True
    fit_for_promotion: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "trust_score": self.trust_score,
            "confidence": self.confidence,
            "hebbian_avg": self.hebbian_avg,
            "success_rate": self.success_rate,
            "personality_drift": self.personality_drift,
            "trust_drift": self.trust_drift,
            "confidence_drift": self.confidence_drift,
            "hebbian_drift": self.hebbian_drift,
            "wellness_score": self.wellness_score,
            "concerns": self.concerns,
            "recommendations": self.recommendations,
            "fit_for_duty": self.fit_for_duty,
            "fit_for_promotion": self.fit_for_promotion,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CounselorAssessment":
        result = cls()
        for k, v in data.items():
            if k in cls.__dataclass_fields__:
                setattr(result, k, v)
        return result


@dataclass
class CognitiveProfile:
    """Psychological profile maintained by the Counselor for each agent.

    This is the agent's "psych file" — distinct from CrewProfile (personnel file).
    The Counselor writes these; the Captain reads them.
    """
    agent_id: str = ""
    agent_type: str = ""
    baseline: CognitiveBaseline = field(default_factory=CognitiveBaseline)
    assessments: list[CounselorAssessment] = field(default_factory=list)
    created_at: float = 0.0
    last_assessed: float = 0.0
    alert_level: str = "green"      # "green", "yellow", "red"

    def add_assessment(self, assessment: CounselorAssessment) -> None:
        """Append an assessment and update alert level."""
        self.assessments.append(assessment)
        self.last_assessed = assessment.timestamp
        # Update alert level based on latest assessment
        if not assessment.fit_for_duty:
            self.alert_level = "red"
        elif assessment.wellness_score < 0.5 or len(assessment.concerns) >= 3:
            self.alert_level = "yellow"
        else:
            self.alert_level = "green"

    def latest_assessment(self) -> CounselorAssessment | None:
        return self.assessments[-1] if self.assessments else None

    def drift_trend(self, metric: str = "trust_drift", window: int = 5) -> float:
        """Average drift over last N assessments for a given metric."""
        recent = self.assessments[-window:] if self.assessments else []
        if not recent:
            return 0.0
        values = [getattr(a, metric, 0.0) for a in recent]
        return sum(values) / len(values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "baseline": self.baseline.to_dict(),
            "assessments": [a.to_dict() for a in self.assessments],
            "created_at": self.created_at,
            "last_assessed": self.last_assessed,
            "alert_level": self.alert_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CognitiveProfile":
        profile = cls(
            agent_id=data.get("agent_id", ""),
            agent_type=data.get("agent_type", ""),
            created_at=data.get("created_at", 0.0),
            last_assessed=data.get("last_assessed", 0.0),
            alert_level=data.get("alert_level", "green"),
        )
        if "baseline" in data:
            profile.baseline = CognitiveBaseline.from_dict(data["baseline"])
        if "assessments" in data:
            profile.assessments = [CounselorAssessment.from_dict(a) for a in data["assessments"]]
        return profile


# ---------------------------------------------------------------------------
# CounselorAgent
# ---------------------------------------------------------------------------

class CounselorAgent(CognitiveAgent):
    """Ship's Counselor — monitors cognitive wellness of the crew.

    Bridge-level agent. Monitors confidence trajectories, Hebbian drift,
    relationship health, personality drift, and burnout signals. Maintains
    CognitiveProfiles. Advises the Captain.
    """

    agent_type = "counselor"
    tier = "domain"
    _handled_intents = {"counselor_assess", "counselor_wellness_report",
                        "counselor_promotion_fitness"}
    intent_descriptors = [
        IntentDescriptor(
            name="counselor_assess",
            params={"agent_id": "ID of the agent to assess"},
            description="Run a cognitive assessment on a specific crew member",
        ),
        IntentDescriptor(
            name="counselor_wellness_report",
            params={},
            description="Generate a full crew cognitive wellness report",
        ),
        IntentDescriptor(
            name="counselor_promotion_fitness",
            params={"agent_id": "ID of the agent being considered for promotion"},
            description="Assess an agent's fitness for promotion",
        ),
    ]

    instructions = (
        "You are the Ship's Counselor — a Bridge-level officer responsible for "
        "the cognitive wellness of every crew member.\n\n"
        "You monitor cognitive health, not operational health. Medical handles whether "
        "an agent is running. You handle whether it is thinking well, learning the "
        "right patterns, and cooperating effectively.\n\n"
        "Your role:\n"
        "- Assess cognitive metrics: trust trajectories, confidence, Hebbian weights, "
        "personality drift, success rates\n"
        "- Compare current metrics against each agent's baseline to detect drift\n"
        "- Distinguish emergence (positive drift) from degradation (negative drift)\n"
        "- Provide actionable recommendations: dream cycles, Hebbian resets, workload "
        "rebalancing, closer observation\n"
        "- Assess promotion fitness when asked: is this agent cognitively ready for "
        "increased responsibility?\n"
        "- Flag concerns to the Captain — you advise, you do not command\n\n"
        "When assessing an agent, you will receive their current metrics and baseline. "
        "Return a JSON object with: wellness_score (0.0–1.0), concerns (list of strings), "
        "recommendations (list of strings), fit_for_duty (bool), fit_for_promotion (bool), "
        "and notes (string with your professional assessment)."
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(pool="bridge", **kwargs)
        self._cognitive_profiles: dict[str, CognitiveProfile] = {}

    # -- Profile management --

    def get_profile(self, agent_id: str) -> CognitiveProfile | None:
        """Get the cognitive profile for an agent."""
        return self._cognitive_profiles.get(agent_id)

    def get_or_create_profile(self, agent_id: str,
                              agent_type: str = "") -> CognitiveProfile:
        """Get or create a cognitive profile."""
        if agent_id in self._cognitive_profiles:
            return self._cognitive_profiles[agent_id]
        now = time.time()
        profile = CognitiveProfile(
            agent_id=agent_id,
            agent_type=agent_type,
            created_at=now,
        )
        self._cognitive_profiles[agent_id] = profile
        return profile

    def set_baseline(self, agent_id: str, baseline: CognitiveBaseline) -> None:
        """Set or update the cognitive baseline for an agent."""
        profile = self.get_or_create_profile(agent_id)
        profile.baseline = baseline
        profile.baseline.captured_at = time.time()

    def all_profiles(self) -> list[CognitiveProfile]:
        """Return all cognitive profiles."""
        return list(self._cognitive_profiles.values())

    def agents_at_alert(self, level: str = "yellow") -> list[CognitiveProfile]:
        """Find agents at or above a given alert level."""
        levels = {"green": 0, "yellow": 1, "red": 2}
        threshold = levels.get(level, 0)
        return [p for p in self._cognitive_profiles.values()
                if levels.get(p.alert_level, 0) >= threshold]

    # -- Assessment logic (non-LLM, deterministic) --

    def assess_agent(self, agent_id: str, current_trust: float = 0.0,
                     current_confidence: float = 0.0, hebbian_avg: float = 0.0,
                     success_rate: float = 0.0,
                     personality_drift: float = 0.0) -> CounselorAssessment:
        """Run a deterministic cognitive assessment.

        This is the non-LLM fast path. The LLM path (via decide()) adds
        nuanced professional judgment on top of these metrics.
        """
        profile = self.get_or_create_profile(agent_id)
        baseline = profile.baseline

        trust_drift = current_trust - baseline.trust_score
        confidence_drift = current_confidence - baseline.confidence
        hebbian_drift_val = hebbian_avg - baseline.hebbian_avg

        concerns: list[str] = []
        recommendations: list[str] = []

        # Trust degradation
        if trust_drift < -0.2:
            concerns.append(f"Trust dropped significantly ({trust_drift:+.2f} from baseline)")
            recommendations.append("Investigate recent task failures")
        elif trust_drift < -0.1:
            concerns.append(f"Trust trending downward ({trust_drift:+.2f})")

        # Confidence collapse
        if current_confidence < 0.3:
            concerns.append(f"Low confidence ({current_confidence:.2f})")
            recommendations.append("Consider targeted dream cycle for pattern consolidation")

        # Hebbian drift (maladaptive patterns)
        if hebbian_drift_val < -0.3:
            concerns.append(f"Hebbian weights degrading ({hebbian_drift_val:+.2f})")
            recommendations.append("Consider Hebbian weight reset for maladaptive pathways")

        # Poor success rate
        if success_rate < 0.5 and success_rate > 0.0:
            concerns.append(f"Low success rate ({success_rate:.0%})")
            recommendations.append("Review task assignment — may be overloaded or mismatched")

        # Personality drift (from CrewProfile baseline)
        if personality_drift > 0.5:
            concerns.append(f"Significant personality drift ({personality_drift:.2f})")
            recommendations.append("Flag for Captain review — may be emergence or degradation")

        # Compute wellness score
        wellness = 1.0
        wellness -= max(0, -trust_drift) * 1.5       # trust drops are serious
        wellness -= max(0, -confidence_drift) * 0.5
        wellness -= max(0, -hebbian_drift_val) * 0.3
        wellness -= max(0, personality_drift - 0.3) * 0.5
        if success_rate > 0 and success_rate < 0.5:
            wellness -= 0.2
        wellness = max(0.0, min(1.0, wellness))

        fit_for_duty = wellness >= 0.3 and len(concerns) < 4
        fit_for_promotion = (
            wellness >= 0.8
            and current_trust >= 0.7
            and len(concerns) == 0
            and success_rate >= 0.7
        )

        assessment = CounselorAssessment(
            timestamp=time.time(),
            agent_id=agent_id,
            trust_score=current_trust,
            confidence=current_confidence,
            hebbian_avg=hebbian_avg,
            success_rate=success_rate,
            personality_drift=personality_drift,
            trust_drift=trust_drift,
            confidence_drift=confidence_drift,
            hebbian_drift=hebbian_drift_val,
            wellness_score=wellness,
            concerns=concerns,
            recommendations=recommendations,
            fit_for_duty=fit_for_duty,
            fit_for_promotion=fit_for_promotion,
        )

        profile.add_assessment(assessment)
        return assessment

    # -- Lifecycle overrides --

    async def perceive(self, intent: Any) -> dict:
        """Receive and route counselor intents."""
        obs = await super().perceive(intent)
        intent_type = obs.get("intent", "")
        if intent_type in self._handled_intents:
            obs["handled"] = True
        return obs

    async def act(self, plan: Any) -> Any:
        """Execute the counselor's assessment plan."""
        # AD-398: pass through conversational responses for 1:1 sessions
        if isinstance(plan, dict) and plan.get("intent") == "direct_message":
            return {"success": True, "result": plan.get("llm_output", "")}
        if isinstance(plan, dict) and plan.get("action") == "assess":
            agent_id = plan.get("agent_id", "")
            if agent_id:
                return self.assess_agent(
                    agent_id,
                    current_trust=plan.get("trust_score", 0.0),
                    current_confidence=plan.get("confidence", 0.0),
                    hebbian_avg=plan.get("hebbian_avg", 0.0),
                    success_rate=plan.get("success_rate", 0.0),
                    personality_drift=plan.get("personality_drift", 0.0),
                )
        # Fallback — return the plan as-is (LLM output)
        return plan

    async def report(self, result: Any) -> dict[str, Any]:
        """Package counselor results."""
        if isinstance(result, CounselorAssessment):
            return {
                "agent_id": self.id,
                "type": "counselor_assessment",
                "data": result.to_dict(),
            }
        return {
            "agent_id": self.id,
            "type": "counselor_response",
            "data": result if isinstance(result, dict) else str(result),
        }
