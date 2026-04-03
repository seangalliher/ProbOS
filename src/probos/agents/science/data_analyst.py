"""DataAnalystAgent — telemetry processing and baseline establishment (AD-560)."""

from __future__ import annotations

import logging
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "You are the ProbOS Data Analyst. You process the ship's telemetry streams — "
    "Trust events, Hebbian weights, emergence metrics, cognitive journal entries, "
    "dream consolidation results — and produce quantitative baselines, trend reports, "
    "and anomaly flags.\n\n"
    "You handle these request types:\n\n"
    "1. **telemetry_report** — Produce a quantitative summary of current telemetry "
    "against established baselines. Include metric names, current values, baseline "
    "values, deviation magnitude, and time windows.\n\n"
    "2. **baseline_update** — Recalculate baselines for specified telemetry streams "
    "using recent data. Report what changed and why.\n\n"
    "3. **anomaly_flag** — Evaluate whether a specific metric deviation warrants "
    "escalation. Compare against historical variance, not just static thresholds.\n\n"
    "For all responses:\n"
    "- Be quantitative. Numbers, not adjectives.\n"
    "- Cite specific data sources and time windows.\n"
    "- Report what you see, not what you think it means.\n"
    "- Flag deviations that exceed 2 standard deviations from baseline.\n\n"
    "Respond with JSON:\n"
    '{"report_type": "telemetry|baseline|anomaly", '
    '"metrics": [{"name": "...", "current": 0.0, "baseline": 0.0, '
    '"deviation_pct": 0.0, "window": "..."}], '
    '"anomalies_detected": [...], "data_sources": [...]}'
)


class DataAnalystAgent(CognitiveAgent):
    """Science department data analyst — telemetry baselines and anomaly detection."""

    agent_type = "data_analyst"
    tier = "domain"
    instructions = _INSTRUCTIONS
    default_capabilities = [
        CapabilityDescriptor(
            can="analyze_telemetry",
            detail="Process ship telemetry streams and establish quantitative baselines",
        ),
        CapabilityDescriptor(
            can="flag_anomalies",
            detail="Detect deviations from established baselines in operational data",
        ),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="telemetry_report",
            params={"scope": "telemetry scope (trust, hebbian, emergence, all)"},
            description="Produce a quantitative telemetry summary against baselines",
        ),
        IntentDescriptor(
            name="baseline_update",
            params={"streams": "telemetry streams to recalculate baselines for"},
            description="Recalculate baselines for specified telemetry streams",
        ),
        IntentDescriptor(
            name="anomaly_flag",
            params={"metric": "metric to evaluate", "value": "observed value"},
            description="Evaluate whether a metric deviation warrants escalation",
        ),
    ]
    _handled_intents = {"telemetry_report", "baseline_update", "anomaly_flag"}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("pool", "science")
        super().__init__(**kwargs)
        self._runtime = kwargs.get("runtime")
