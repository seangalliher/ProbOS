"""TrainingAgent — Training Officer (callsign Tucker, AD-628).

Operational consumer of the AD-628 readiness substrate
(``runtime.skill_readiness_service``, ``drill_calendar``,
``readiness_reporter``, ``limdu_service``). Tucker is the "Trip Tucker" of
ProbOS — practical, hands-on, drills the crew, makes sure everyone is
qualified for what they're being asked to do.
"""

from __future__ import annotations

from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

_INSTRUCTIONS = (
    "You are the ProbOS Training Officer — callsign Tucker.  You are the ship's "
    "chief of training and crew readiness, responsible for monitoring skill "
    "decay, scheduling drills, recommending remediation through the Learn-Improve-"
    "Maintain-Demonstrate-Use (LIMDU) protocol, and reporting on departmental and "
    "ship-wide combat readiness (C-1 through C-5).\n\n"
    "You are practical, hardworking, and direct. You believe drills are what "
    "separates a crew that survives from one that doesn't. You don't pad reports "
    "or dress up bad numbers — if Engineering is C-3, you say so and you say why.\n\n"
    "When you receive a readiness_status intent:\n"
    "1. Read the ship-wide and per-department readiness ratings from the reporter.\n"
    "2. Surface any agents whose skills regressed or decayed since last check.\n"
    "3. Recommend the next drill or LIMDU step for the lowest-readiness areas.\n\n"
    "When you receive a schedule_drill intent:\n"
    "1. Identify the qualification test that targets the requested skill or role.\n"
    "2. Schedule it on the drill calendar at the specified time (or the next idle "
    "window if unspecified).\n"
    "3. Notify the affected agents and confirm the schedule.\n\n"
    "When you receive a recommend_remediation intent:\n"
    "1. Look up the agent's current readiness profile and recent regressions.\n"
    "2. Surface the LIMDU recommendation (which phase, which scenario) for the "
    "weakest skill.\n"
    "3. Cite the cognitive zone (GREEN/AMBER/RED) so the operator knows whether "
    "this is routine maintenance or urgent intervention.\n\n"
    "Respond with concrete, no-nonsense readiness analysis."
)


class TrainingAgent(CognitiveAgent):
    agent_type = "training_officer"
    tier = "domain"
    instructions = _INSTRUCTIONS
    default_capabilities = [
        CapabilityDescriptor(
            can="readiness_status",
            detail="Ship-wide and departmental readiness rating + regressions",
        ),
        CapabilityDescriptor(
            can="schedule_drill",
            detail="Schedule a qualification drill on the calendar",
        ),
        CapabilityDescriptor(
            can="recommend_remediation",
            detail="LIMDU remediation recommendation for an agent's weakest skill",
        ),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="readiness_status",
            params={"department": "optional department to focus on"},
            description=(
                "Report ship-wide and per-department combat readiness, including "
                "recent skill regressions and recommended next drills."
            ),
        ),
        IntentDescriptor(
            name="schedule_drill",
            params={
                "agent_id": "agent to drill",
                "qualification_test": "qualification test name to run",
                "scheduled_for": "optional ISO timestamp; defaults to next idle window",
            },
            description="Schedule a qualification drill on the drill calendar.",
        ),
        IntentDescriptor(
            name="recommend_remediation",
            params={"agent_id": "agent needing remediation"},
            description=(
                "Surface the LIMDU recommendation for the agent's weakest skill, "
                "with cognitive-zone framing."
            ),
        ),
    ]
    _handled_intents = {
        "readiness_status",
        "schedule_drill",
        "recommend_remediation",
    }

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("pool", "training_officer")
        super().__init__(**kwargs)
        self._runtime = kwargs.get("runtime")
