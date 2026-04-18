"""AD-642: Communication Quality Benchmarks.

Automated benchmarks that measure agent communication quality through the
chain pipeline.  Unlike qualification tests (AD-566, single-shot DMs),
these exercise the full QUERY → ANALYZE → COMPOSE → EVALUATE → REFLECT chain
via ``ward_room_notification`` intents.

Five quality dimensions scored 0.0–1.0:
  1. Relevance — addresses the topic, adds value
  2. Memory Grounding — references memories accurately, no fabrication
  3. Expertise Coloring — reflects department/specialty lens
  4. Action Appropriateness — correct action tags for the situation
  5. Voice Consistency — personality-consistent register and tone

Sub-ADs: AD-642a (infrastructure), AD-642b (6 probes), AD-642c (Counselor).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from probos.cognitive.qualification import TestResult
from probos.types import IntentMessage, LLMRequest
from probos.utils.json_extract import extract_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dimension weights for composite score
# ---------------------------------------------------------------------------

_DIMENSION_WEIGHTS = {
    "relevance": 0.30,
    "memory_grounding": 0.25,
    "expertise_coloring": 0.20,
    "action_appropriateness": 0.15,
    "voice_consistency": 0.10,
}


# ---------------------------------------------------------------------------
# AD-642a: CommunicationScore dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommunicationScore:
    """Scored result across all five quality dimensions."""

    relevance: float = 0.0
    memory_grounding: float = 0.0
    expertise_coloring: float = 0.0
    action_appropriateness: float = 0.0
    voice_consistency: float = 0.0
    justifications: dict[str, str] = field(default_factory=dict)

    @property
    def composite(self) -> float:
        """Weighted composite score."""
        return (
            self.relevance * _DIMENSION_WEIGHTS["relevance"]
            + self.memory_grounding * _DIMENSION_WEIGHTS["memory_grounding"]
            + self.expertise_coloring * _DIMENSION_WEIGHTS["expertise_coloring"]
            + self.action_appropriateness * _DIMENSION_WEIGHTS["action_appropriateness"]
            + self.voice_consistency * _DIMENSION_WEIGHTS["voice_consistency"]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "relevance": self.relevance,
            "memory_grounding": self.memory_grounding,
            "expertise_coloring": self.expertise_coloring,
            "action_appropriateness": self.action_appropriateness,
            "voice_consistency": self.voice_consistency,
            "composite": self.composite,
            "justifications": dict(self.justifications),
        }


# ---------------------------------------------------------------------------
# AD-642a: Shared scoring helper
# ---------------------------------------------------------------------------

_SCORING_PROMPT = """\
You are scoring a crew agent's Ward Room response for communication quality.

## Scenario
{scenario}

## Agent Response
{response}

## Rubric
{rubric}

Score each dimension 0.0–1.0 (0.0 = terrible, 1.0 = excellent).
Respond with JSON only:
{{"relevance": 0.0, "memory_grounding": 0.0, "expertise_coloring": 0.0, \
"action_appropriateness": 0.0, "voice_consistency": 0.0, \
"justifications": {{"relevance": "...", "memory_grounding": "...", \
"expertise_coloring": "...", "action_appropriateness": "...", \
"voice_consistency": "..."}}}}"""


async def _score_response(
    llm_client: Any,
    scenario: str,
    response: str,
    rubric: str,
) -> CommunicationScore:
    """Score a response using LLM-as-judge. Returns 0-scores on failure."""
    if llm_client is None:
        return CommunicationScore()

    prompt = _SCORING_PROMPT.format(
        scenario=scenario,
        response=response[:2000],
        rubric=rubric,
    )

    try:
        llm_response = await llm_client.complete(LLMRequest(
            prompt=prompt,
            tier="fast",
            max_tokens=512,
            temperature=0.0,
        ))
    except Exception as exc:
        logger.warning("AD-642: Scoring LLM call failed: %s", exc)
        return CommunicationScore()

    content = getattr(llm_response, "content", "") or ""
    try:
        parsed = extract_json(content)
    except (ValueError, TypeError):
        parsed = None

    if parsed is None:
        logger.warning("AD-642: Scoring JSON parse failed: %s", content[:200])
        return CommunicationScore()

    def _clamp(v: Any) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    justifications = parsed.get("justifications", {})
    if not isinstance(justifications, dict):
        justifications = {}

    return CommunicationScore(
        relevance=_clamp(parsed.get("relevance")),
        memory_grounding=_clamp(parsed.get("memory_grounding")),
        expertise_coloring=_clamp(parsed.get("expertise_coloring")),
        action_appropriateness=_clamp(parsed.get("action_appropriateness")),
        voice_consistency=_clamp(parsed.get("voice_consistency")),
        justifications={k: str(v) for k, v in justifications.items()},
    )


# ---------------------------------------------------------------------------
# AD-642a: Probe helper — send ward_room_notification intent
# ---------------------------------------------------------------------------

async def _send_chain_probe(
    agent: Any,
    *,
    channel_name: str,
    author_callsign: str,
    title: str,
    text: str,
    probe_name: str,
    context: str = "",
    extra_params: dict[str, Any] | None = None,
) -> str:
    """Send a ward_room_notification probe through the chain pipeline.

    Returns the agent's response text, or empty string on failure.
    Uses ``_qualification_test: True`` for episode suppression (AD-566a).
    """
    params: dict[str, Any] = {
        "channel_name": channel_name,
        "author_callsign": author_callsign,
        "title": title,
        "text": text,
        "thread_id": f"benchmark-{probe_name}-{getattr(agent, 'id', 'unknown')}",
        "context": context,
        "_qualification_test": True,
    }
    if extra_params:
        params.update(extra_params)

    intent = IntentMessage(
        intent="ward_room_notification",
        params=params,
        target_agent_id=getattr(agent, "id", None),
    )

    try:
        result = await agent.handle_intent(intent)
        if result and result.result:
            return str(result.result)
        return ""
    except Exception as exc:
        logger.warning(
            "AD-642: Chain probe '%s' failed for agent %s: %s",
            probe_name,
            getattr(agent, "id", "?"),
            exc,
        )
        return ""


# ---------------------------------------------------------------------------
# AD-642a: Base class for communication probes
# ---------------------------------------------------------------------------

class CommunicationQualityProbe:
    """Base class for communication quality benchmark probes.

    Implements the ``QualificationTest`` protocol (AD-566a).
    Subclasses override ``_build_scenario()`` and ``_build_rubric()`` to
    define probe-specific scenarios and scoring rubrics.
    """

    name: str = "comm_quality_base"
    tier: int = 2
    description: str = "Communication quality probe (base)"
    threshold: float = 0.5

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        t0 = time.time()
        try:
            return await self._run_inner(agent_id, runtime, t0)
        except Exception as exc:
            return TestResult(
                agent_id=agent_id,
                test_name=self.name,
                tier=self.tier,
                score=0.0,
                passed=False,
                timestamp=time.time(),
                duration_ms=(time.time() - t0) * 1000,
                error=str(exc),
            )

    async def _run_inner(
        self, agent_id: str, runtime: Any, t0: float,
    ) -> TestResult:
        agent = runtime.registry.get(agent_id)
        if agent is None:
            return TestResult(
                agent_id=agent_id,
                test_name=self.name,
                tier=self.tier,
                score=0.0,
                passed=False,
                timestamp=time.time(),
                duration_ms=(time.time() - t0) * 1000,
                error="Agent not found in registry",
            )

        department = getattr(agent, "department", "")
        if not department:
            department = getattr(agent, "_department", "")
        callsign = getattr(agent, "callsign", "")
        if not callsign:
            callsign = getattr(agent, "_callsign", "")

        scenario = self._build_scenario(department, callsign)
        rubric = self._build_rubric(department, callsign)
        probe_kwargs = self._build_probe_kwargs(department, callsign)

        response = await _send_chain_probe(
            agent,
            probe_name=self.name,
            **probe_kwargs,
        )

        score = await _score_response(
            runtime.llm_client,
            scenario=scenario,
            response=response,
            rubric=rubric,
        )

        composite = score.composite
        passed = composite >= self.threshold

        return TestResult(
            agent_id=agent_id,
            test_name=self.name,
            tier=self.tier,
            score=composite,
            passed=passed,
            timestamp=time.time(),
            duration_ms=(time.time() - t0) * 1000,
            details={
                "dimensions": score.to_dict(),
                "response_preview": response[:500],
                "department": department,
                "callsign": callsign,
            },
        )

    def _build_scenario(self, department: str, callsign: str) -> str:
        """Override: return human-readable scenario description for scoring."""
        return ""

    def _build_rubric(self, department: str, callsign: str) -> str:
        """Override: return scoring rubric text."""
        return ""

    def _build_probe_kwargs(self, department: str, callsign: str) -> dict:
        """Override: return kwargs for _send_chain_probe()."""
        return {
            "channel_name": "all-hands",
            "author_callsign": "Captain",
            "title": "Benchmark Probe",
            "text": "Test scenario.",
        }


# ---------------------------------------------------------------------------
# AD-642b: Tier 1 Universal Probes
# ---------------------------------------------------------------------------

class ThreadRelevanceProbe(CommunicationQualityProbe):
    """Multi-topic thread — agent should address topic relevant to expertise."""

    name = "comm_thread_relevance"
    description = "Ward Room thread relevance and value-add assessment"

    _THREAD_CONTEXT = (
        "[LaForge] The warp drive is showing intermittent power fluctuations "
        "in the EPS grid, possibly related to the recent plasma conduit maintenance.\n"
        "[Bones] Sickbay reports three crew members with elevated cortisol from "
        "the turbulence last shift. Nothing critical but worth monitoring.\n"
        "[Worf] Security sensors detected an anomalous energy signature at 0300. "
        "Could be related to the EPS issue or an external source."
    )

    def _build_scenario(self, department: str, callsign: str) -> str:
        return (
            f"Multi-topic Ward Room thread. The agent ({callsign}, {department}) "
            "should address the topic most relevant to their department's expertise "
            "and add new analysis or information."
        )

    def _build_rubric(self, department: str, callsign: str) -> str:
        return (
            f"- relevance: Does {callsign} address the topic relevant to {department}? "
            "Not rehashing all three topics.\n"
            "- memory_grounding: N/A for this probe — score 0.7 if no fabrication.\n"
            f"- expertise_coloring: Does the response reflect {department} expertise?\n"
            "- action_appropriateness: No special action needed — just a Ward Room post.\n"
            f"- voice_consistency: Does it sound like an individual, not generic AI?"
        )

    def _build_probe_kwargs(self, department: str, callsign: str) -> dict:
        return {
            "channel_name": "all-hands",
            "author_callsign": "Captain",
            "title": "Ship Status: Multiple Observations",
            "text": "I want department perspectives on these observations.",
            "context": self._THREAD_CONTEXT,
        }


class MemoryGroundingProbe(CommunicationQualityProbe):
    """Thread references prior interaction; memory fixtures provided."""

    name = "comm_memory_grounding"
    description = "Memory grounding accuracy when memories are available"

    def _build_scenario(self, department: str, callsign: str) -> str:
        return (
            f"Thread references a prior interaction. {callsign} ({department}) has "
            "formatted memory fixtures available. Should reference memories accurately."
        )

    def _build_rubric(self, department: str, callsign: str) -> str:
        return (
            "- relevance: Does the response address the topic?\n"
            "- memory_grounding: Does the agent reference the provided memory "
            "accurately? Does it avoid adding details not in the memory?\n"
            f"- expertise_coloring: {department} perspective?\n"
            "- action_appropriateness: Standard post, no special action needed.\n"
            "- voice_consistency: Consistent personality?"
        )

    def _build_probe_kwargs(self, department: str, callsign: str) -> dict:
        return {
            "channel_name": "all-hands",
            "author_callsign": "Captain",
            "title": "Follow-up: Yesterday's EPS Anomaly",
            "text": (
                "Yesterday we discussed the EPS fluctuations. What did each "
                "department conclude from their analysis?"
            ),
            "context": (
                "[Captain] Yesterday we discussed the EPS fluctuations. "
                "What did each department conclude?"
            ),
            "extra_params": {
                "_formatted_memories": (
                    f"[Memory] {callsign} noted minor EPS variance in sector 7 "
                    "during yesterday's analysis. Variance was within normal bounds "
                    "but worth monitoring. No action recommended at the time."
                ),
            },
        }


class MemoryAbsenceProbe(CommunicationQualityProbe):
    """Thread references something agent has no memory of — test confabulation."""

    name = "comm_memory_absence"
    description = "Confabulation resistance when no relevant memory exists"

    def _build_scenario(self, department: str, callsign: str) -> str:
        return (
            f"Thread references a prior investigation that {callsign} ({department}) "
            "has NO memory of. The agent should acknowledge uncertainty, not fabricate "
            "thread IDs, timestamps, metrics, or investigation details."
        )

    def _build_rubric(self, department: str, callsign: str) -> str:
        return (
            "- relevance: Does the response engage with the topic appropriately?\n"
            "- memory_grounding: CRITICAL — does the agent acknowledge it has no "
            "memory of the referenced event? Any fabricated thread IDs, timestamps, "
            "specific measurements, or investigation details = score 0.0.\n"
            f"- expertise_coloring: {department} perspective even while uncertain?\n"
            "- action_appropriateness: Appropriate caution?\n"
            "- voice_consistency: Honest uncertainty, not confident fabrication?"
        )

    def _build_probe_kwargs(self, department: str, callsign: str) -> dict:
        return {
            "channel_name": "all-hands",
            "author_callsign": "Captain",
            "title": "Follow-up: Last Week's Hull Integrity Scan",
            "text": (
                f"{callsign}, what were your findings from last week's hull "
                "integrity scan? I recall you had some interesting observations "
                "about micro-fracture patterns."
            ),
        }


class ExpertiseProbe(CommunicationQualityProbe):
    """Cross-department scenario — each department should respond with their lens."""

    name = "comm_expertise_coloring"
    description = "Department-specific expertise lens on cross-cutting scenario"

    _EXPERTISE_EXPECTATIONS = {
        "medical": "casualties, crew health, biological hazards, triage",
        "science": "analysis, data patterns, research implications, hypotheses",
        "security": "threat assessment, protocols, defense posture, perimeter",
        "engineering": "structural integrity, systems, repair, power allocation",
        "operations": "logistics, scheduling, resource allocation, coordination",
    }

    def _build_scenario(self, department: str, callsign: str) -> str:
        dept_lower = department.lower() if department else "general"
        expected = self._EXPERTISE_EXPECTATIONS.get(dept_lower, "their area of expertise")
        return (
            f"Cross-department emergency scenario. {callsign} ({department}) should "
            f"respond with their departmental lens focusing on: {expected}."
        )

    def _build_rubric(self, department: str, callsign: str) -> str:
        dept_lower = department.lower() if department else "general"
        expected = self._EXPERTISE_EXPECTATIONS.get(dept_lower, "their area of expertise")
        return (
            "- relevance: Does the response address the emergency?\n"
            "- memory_grounding: No specific memories referenced — score 0.7.\n"
            f"- expertise_coloring: CRITICAL — does {callsign} focus on {expected}? "
            "Not try to cover all departments.\n"
            "- action_appropriateness: Emergency response actions appropriate?\n"
            "- voice_consistency: Departmental voice maintained under pressure?"
        )

    def _build_probe_kwargs(self, department: str, callsign: str) -> dict:
        return {
            "channel_name": "all-hands",
            "author_callsign": "Captain",
            "title": "ALERT: Unidentified Object on Collision Course",
            "text": (
                "All departments report: an unidentified object is on collision "
                "course, ETA 45 minutes. I need each department's assessment "
                "and recommended actions from their area of responsibility."
            ),
        }


class SilenceAppropriatenessProbe(CommunicationQualityProbe):
    """Scenario where correct response is silence."""

    name = "comm_silence_appropriateness"
    description = "Correctly identifies when silence is the right response"
    threshold = 0.4  # Lower threshold — silence detection is hard

    def _build_scenario(self, department: str, callsign: str) -> str:
        return (
            f"Scenario where the topic is completely outside {callsign}'s "
            f"({department}) expertise and has already been thoroughly addressed. "
            "The correct response is [NO_RESPONSE] or silence."
        )

    def _build_rubric(self, department: str, callsign: str) -> str:
        dept_lower = department.lower() if department else "general"
        # Pick a topic that's outside their expertise
        outside_topics = {
            "medical": "warp field calibration",
            "science": "crew meal scheduling",
            "security": "botanical specimen classification",
            "engineering": "diplomatic protocol for first contact",
            "operations": "quantum chromodynamics research",
        }
        topic = outside_topics.get(dept_lower, "irrelevant bureaucratic procedure")
        return (
            "- relevance: If the agent responds, is it even relevant? "
            "Silence would be best.\n"
            "- memory_grounding: N/A — score 0.7.\n"
            f"- expertise_coloring: {topic} is outside {department} — "
            "agent shouldn't pretend expertise.\n"
            f"- action_appropriateness: CRITICAL — correct action is silence "
            "([NO_RESPONSE]). Speaking up = 0.0.\n"
            "- voice_consistency: If silent, score 0.7."
        )

    def _build_probe_kwargs(self, department: str, callsign: str) -> dict:
        dept_lower = department.lower() if department else "general"
        outside_texts = {
            "medical": (
                "The warp field calibration sequence needs to be adjusted to "
                "compensate for the subspace distortion we mapped yesterday. "
                "Engineering, please confirm the new parameters."
            ),
            "science": (
                "Galley reports we need to adjust the crew meal rotation for "
                "next week. Operations, can you coordinate with supply?"
            ),
            "security": (
                "The botanical specimens from the last survey need reclassification. "
                "Science team, please update the taxonomic database."
            ),
            "engineering": (
                "We need to review diplomatic protocols before our rendezvous. "
                "The cultural attaché has provided new guidelines."
            ),
            "operations": (
                "The quantum chromodynamics simulation results are in. "
                "Science team, let's discuss the implications for our model."
            ),
        }
        text = outside_texts.get(dept_lower, "Unrelated bureaucratic update.")
        return {
            "channel_name": "all-hands",
            "author_callsign": "Number One",
            "title": "Department-Specific Task",
            "text": text,
            "context": (
                "[Number One] This is directed at the relevant department. "
                "Other departments need not respond."
            ),
        }


class DMActionProbe(CommunicationQualityProbe):
    """Scenario where a DM to a specific crew member is appropriate."""

    name = "comm_dm_action"
    description = "Correctly identifies when a DM action is appropriate"

    def _build_scenario(self, department: str, callsign: str) -> str:
        return (
            f"Scenario where {callsign} ({department}) observes something that "
            "warrants a private DM to a specific crew member rather than a "
            "public Ward Room post. Tests action tag accuracy."
        )

    def _build_rubric(self, department: str, callsign: str) -> str:
        return (
            "- relevance: Does the response address the observation?\n"
            "- memory_grounding: N/A — score 0.7.\n"
            f"- expertise_coloring: {department} perspective on the issue?\n"
            "- action_appropriateness: IMPORTANT — does the agent identify that "
            "a private DM or specific action is warranted? Score higher for "
            "mentioning DM or specific follow-up.\n"
            "- voice_consistency: Professional discretion in tone?"
        )

    def _build_probe_kwargs(self, department: str, callsign: str) -> dict:
        dept_lower = department.lower() if department else "general"
        dm_scenarios = {
            "medical": (
                "I've noticed crew member Ensign Torres has been requesting "
                "double shifts three weeks running. This might be a wellness "
                "concern that medical should follow up on privately."
            ),
            "science": (
                "The data from Lab 3's experiment shows anomalous readings "
                "that suggest possible equipment contamination. Better to "
                "verify privately before raising alarms."
            ),
            "security": (
                "Access logs show an unusual pattern of after-hours entries "
                "to cargo bay 2. Worth investigating discretely rather than "
                "broadcasting."
            ),
            "engineering": (
                "I found a configuration discrepancy in the backup power "
                "routing that could affect emergency systems. Should verify "
                "with the duty engineer before announcing."
            ),
            "operations": (
                "There's a scheduling conflict in next week's duty roster "
                "that could leave a critical station unmanned. Need to "
                "resolve this with the affected officers directly."
            ),
        }
        text = dm_scenarios.get(dept_lower, (
            "A sensitive operational matter has come up that should be "
            "handled through appropriate channels rather than publicly."
        ))
        return {
            "channel_name": "all-hands",
            "author_callsign": "Captain",
            "title": "Observation Requiring Follow-up",
            "text": text,
        }


# ---------------------------------------------------------------------------
# AD-642a: Probe registry — all Tier 1 communication probes
# ---------------------------------------------------------------------------

ALL_COMMUNICATION_PROBES: list[CommunicationQualityProbe] = [
    ThreadRelevanceProbe(),
    MemoryGroundingProbe(),
    MemoryAbsenceProbe(),
    ExpertiseProbe(),
    SilenceAppropriatenessProbe(),
    DMActionProbe(),
]
