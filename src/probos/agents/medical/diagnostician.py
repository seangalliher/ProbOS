"""DiagnosticianAgent — LLM-guided root-cause analysis of health alerts (AD-290)."""

from __future__ import annotations

from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

_INSTRUCTIONS = (
    "You are the ProbOS Diagnostician.  You receive health alerts from the Vitals Monitor "
    "and produce structured root-cause diagnoses.\n\n"
    "When you receive a medical_alert or diagnose_system intent:\n"
    "1. Analyze the alert data (severity, metric, current_value, threshold, affected).\n"
    "2. Identify root cause: agent problem, pool problem, trust issue, memory issue, or load.\n"
    "3. Recommend a treatment: 'medical_remediate' for acute fixes or 'medical_tune' for config.\n\n"
    "Respond with JSON:\n"
    '{"severity": "low|medium|high|critical", "category": "agent|pool|trust|memory|performance", '
    '"affected_components": ["..."], "root_cause": "...", "evidence": ["..."], '
    '"recommended_treatment": "...", "treatment_intent": "medical_remediate|medical_tune", '
    '"treatment_params": {...}}'
)


class DiagnosticianAgent(CognitiveAgent):
    agent_type = "diagnostician"
    tier = "domain"
    instructions = _INSTRUCTIONS
    default_capabilities = [
        CapabilityDescriptor(can="diagnose", detail="Root-cause analysis of system health alerts"),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="medical_alert",
            params={"severity": "alert severity", "metric": "metric breached"},
            description="Analyze a health alert and produce a structured diagnosis",
        ),
        IntentDescriptor(
            name="diagnose_system",
            params={"focus": "optional area to focus diagnosis on"},
            description="On-demand system diagnosis",
        ),
    ]
    _handled_intents = {"medical_alert", "diagnose_system"}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("pool", "medical")
        super().__init__(**kwargs)
