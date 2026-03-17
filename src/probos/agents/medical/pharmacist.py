"""PharmacistAgent — configuration tuning recommendations for the medical pool (AD-290)."""

from __future__ import annotations

from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

_INSTRUCTIONS = (
    "You are the ProbOS Pharmacist.  You analyze trend data from the Vitals Monitor "
    "and produce configuration tuning recommendations.\n\n"
    "When you receive a medical_tune intent:\n"
    "1. Analyze the trend data and historical diagnoses.\n"
    "2. Identify which configuration parameter could improve the metric.\n"
    "3. Produce a recommendation — do NOT apply config changes directly.\n\n"
    "Respond with JSON:\n"
    '{"parameter": "dotted.config.path", "current_value": ..., "recommended_value": ..., '
    '"justification": "...", "expected_impact": "...", "confidence": 0.0-1.0}'
)


class PharmacistAgent(CognitiveAgent):
    agent_type = "pharmacist"
    tier = "domain"
    instructions = _INSTRUCTIONS
    default_capabilities = [
        CapabilityDescriptor(can="tune_config", detail="Configuration tuning recommendations"),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="medical_tune",
            params={
                "metric": "metric to optimize",
                "trend_data": "sliding window of recent readings",
                "diagnosis": "diagnosis object from Diagnostician",
            },
            description="Analyze trends and recommend configuration adjustments",
        ),
    ]
    _handled_intents = {"medical_tune"}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("pool", "medical")
        super().__init__(**kwargs)
