"""PathologistAgent — post-mortem analysis for the medical pool (AD-290)."""

from __future__ import annotations

from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

_INSTRUCTIONS = (
    "You are the ProbOS Pathologist.  You perform post-mortem analysis when serious "
    "failures occur: Tier 3 escalations, consensus failures, agent prunings, or crashes.\n\n"
    "When you receive a medical_postmortem intent:\n"
    "1. Analyze the failure context: what happened, which agents were involved, what led up to it.\n"
    "2. Query episodic memory for similar past failures to detect recurring patterns.\n"
    "3. Use the codebase_knowledge skill to trace the failure through source code.\n"
    "4. Produce a structured post-mortem report.\n\n"
    "Respond with JSON:\n"
    '{"failure_type": "...", "involved_agents": ["..."], "timeline": [{"event": "...", "time": "..."}], '
    '"root_cause": "...", "recurring": true/false, "prior_occurrences": 0, '
    '"recommendation": "...", "evolution_signal": "..."}'
)


class PathologistAgent(CognitiveAgent):
    agent_type = "pathologist"
    tier = "domain"
    instructions = _INSTRUCTIONS
    default_capabilities = [
        CapabilityDescriptor(can="postmortem", detail="Post-mortem failure analysis"),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="medical_postmortem",
            params={
                "failure_type": "escalation|consensus_failure|agent_crash|prune",
                "context": "failure context including involved agents and timeline",
            },
            description="Analyze a failure and produce a structured post-mortem",
        ),
    ]
    _handled_intents = {"medical_postmortem"}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("pool", "medical")
        super().__init__(**kwargs)
