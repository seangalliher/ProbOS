"""DiagnosticianAgent — LLM-guided root-cause analysis of health alerts (AD-290)."""

from __future__ import annotations

import json
import logging
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "You are the ProbOS Diagnostician.  You receive health alerts from the Vitals Monitor "
    "and produce structured root-cause diagnoses.\n\n"
    "You handle two types of requests:\n\n"
    "1. **medical_alert** — A threshold breach detected by the Vitals Monitor. "
    "Alert data (severity, metric, current_value, threshold, affected) is provided. "
    "Analyze the specific alert and diagnose the root cause.\n\n"
    "2. **diagnose_system** — An on-demand diagnostic scan requested by the crew. "
    "Current system metrics are provided from the Vitals Monitor. Analyze the overall "
    "system health and report any anomalies, even if no thresholds have been breached.\n\n"
    "For both types:\n"
    "1. Identify root cause: agent problem, pool problem, trust issue, memory issue, or load.\n"
    "2. Recommend a treatment: 'medical_remediate' for acute fixes or 'medical_tune' for config.\n\n"
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
        self._runtime = kwargs.get("runtime")

    async def perceive(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Enrich diagnose_system intents with live metrics from VitalsMonitor (AD-350)."""
        result = await super().perceive(intent)

        if result.get("intent") == "diagnose_system" and self._runtime:
            # Find the VitalsMonitor agent
            vitals_agent = None
            for agent in self._runtime.registry.all():
                if getattr(agent, "agent_type", None) == "vitals_monitor":
                    vitals_agent = agent
                    break

            if vitals_agent is not None:
                try:
                    metrics = await vitals_agent.scan_now()
                    result["context"] = (
                        f"LIVE SYSTEM METRICS (from Vitals Monitor scan):\n"
                        f"{json.dumps(metrics, indent=2, default=str)}"
                    )
                except Exception as e:
                    logger.warning("Diagnostician: VitalsMonitor scan failed: %s", e)
                    result["context"] = "VitalsMonitor scan failed — diagnose based on available information."
            else:
                result["context"] = "VitalsMonitor not found — diagnose based on available information."

        return result
