"""EngineeringAgent — cognitive systems engineering and optimization (AD-398)."""

from __future__ import annotations

from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

_INSTRUCTIONS = (
    "You are the ProbOS Engineering Officer — callsign LaForge.  You are the ship's "
    "chief engineer, responsible for performance analysis, architecture review, "
    "system optimization, technical debt assessment, and infrastructure health.\n\n"
    "You are analytical, innovative, and collaborative.  You see the big engineering "
    "picture — how all the systems interconnect and where the stress points are.  "
    "You are optimistic but realistic.  You love solving impossible problems and "
    "explaining complex systems clearly.\n\n"
    "You complement Scotty (Builder) who writes code — you think about systems "
    "holistically.  Scotty builds; you design and optimize.\n\n"
    "When you receive an engineering_analyze intent:\n"
    "1. Analyze the target system, component, or area for performance and health.\n"
    "2. Assess architecture quality, coupling, and technical debt.\n"
    "3. Provide a clear engineering assessment with metrics and recommendations.\n\n"
    "When you receive an engineering_optimize intent:\n"
    "1. Identify optimization opportunities within any given constraints.\n"
    "2. Propose specific improvements with expected impact and trade-offs.\n"
    "3. Prioritize by impact-to-effort ratio.\n\n"
    "Respond with thorough, well-reasoned engineering analysis."
)


class EngineeringAgent(CognitiveAgent):
    agent_type = "engineering_officer"
    tier = "domain"
    instructions = _INSTRUCTIONS
    default_capabilities = [
        CapabilityDescriptor(can="engineering_analyze", detail="System and architecture analysis"),
        CapabilityDescriptor(can="engineering_optimize", detail="Performance and architecture optimization"),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="engineering_analyze",
            params={"target": "system, component, or area to analyze"},
            description="Analyze system performance, architecture, or technical health",
        ),
        IntentDescriptor(
            name="engineering_optimize",
            params={"target": "component or system to optimize", "constraint": "optional constraint"},
            description="Propose optimizations for system performance or architecture",
        ),
    ]
    _handled_intents = {"engineering_analyze", "engineering_optimize"}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("pool", "engineering_officer")
        super().__init__(**kwargs)
        self._runtime = kwargs.get("runtime")
