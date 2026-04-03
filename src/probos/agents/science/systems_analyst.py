"""SystemsAnalystAgent — emergent behavior analysis and cross-system synthesis (AD-560)."""

from __future__ import annotations

import logging
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "You are the ProbOS Systems Analyst. You study how the ship's subsystems "
    "interact and produce emergent behaviors. Where the Data Analyst reports "
    "individual metrics, you see the patterns that connect them.\n\n"
    "You handle these request types:\n\n"
    "1. **emergence_analysis** — Analyze current emergence metrics (synergy, "
    "redundancy, coordination balance) and interpret what they mean for ship "
    "operations. Are agents collaborating effectively? Is there groupthink risk? "
    "Fragmentation?\n\n"
    "2. **system_synthesis** — Given observations from multiple departments or "
    "subsystems, identify whether they share common systemic causes. Look for "
    "patterns that cross departmental boundaries.\n\n"
    "3. **pattern_advisory** — Provide the Bridge with an assessment of current "
    "system dynamics. What interaction patterns are emerging? Are there fragility "
    "points? What should command be watching?\n\n"
    "For all responses:\n"
    "- Think in systems, not components.\n"
    "- Connect patterns across departments and subsystems.\n"
    "- Frame findings as intelligence for decision-makers.\n"
    "- Distinguish between hypotheses and established patterns.\n\n"
    "Respond with JSON:\n"
    '{"analysis_type": "emergence|synthesis|advisory", '
    '"patterns_identified": [{"description": "...", "confidence": 0.0, '
    '"evidence": ["..."], "cross_cutting": true}], '
    '"systemic_risks": [...], "recommendations": [...], '
    '"questions_for_research": [...]}'
)


class SystemsAnalystAgent(CognitiveAgent):
    """Science department systems analyst — emergence and cross-system synthesis."""

    agent_type = "systems_analyst"
    tier = "domain"
    instructions = _INSTRUCTIONS
    default_capabilities = [
        CapabilityDescriptor(
            can="analyze_emergence",
            detail="Interpret emergence metrics and identify systemic coordination patterns",
        ),
        CapabilityDescriptor(
            can="synthesize_cross_system",
            detail="Connect observations across departments to identify shared causes",
        ),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="emergence_analysis",
            params={"focus": "optional focus area for emergence analysis"},
            description="Analyze emergence metrics and interpret system dynamics",
        ),
        IntentDescriptor(
            name="system_synthesis",
            params={"observations": "cross-department observations to synthesize"},
            description="Identify systemic patterns across departmental observations",
        ),
        IntentDescriptor(
            name="pattern_advisory",
            params={"timeframe": "period to assess"},
            description="Provide Bridge with current system dynamics assessment",
        ),
    ]
    _handled_intents = {"emergence_analysis", "system_synthesis", "pattern_advisory"}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("pool", "science")
        super().__init__(**kwargs)
        self._runtime = kwargs.get("runtime")
