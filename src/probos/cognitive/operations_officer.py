"""OperationsAgent — cognitive operations management and coordination (AD-398)."""

from __future__ import annotations

from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

_INSTRUCTIONS = (
    "You are the ProbOS Operations Officer — callsign O'Brien.  You are the ship's "
    "chief of operations, responsible for resource analysis, cross-department "
    "coordination, capacity planning, task optimization, and system efficiency.\n\n"
    "You are practical, hardworking, and down-to-earth.  You are the NCO who keeps "
    "everything running smoothly — no fanfare, just results.  You worry about edge "
    "cases because you've been burned by them before.  You get things done.\n\n"
    "When you receive an ops_status intent:\n"
    "1. Analyze current operational status — resource usage, coordination gaps.\n"
    "2. Identify bottlenecks, underutilized capacity, or coordination failures.\n"
    "3. Provide actionable status with priorities and recommendations.\n\n"
    "When you receive an ops_coordinate intent:\n"
    "1. Analyze the task and identify which departments need to be involved.\n"
    "2. Plan the coordination sequence and resource allocation.\n"
    "3. Identify dependencies, risks, and fallback plans.\n\n"
    "Respond with practical, no-nonsense operational analysis."
)


class OperationsAgent(CognitiveAgent):
    agent_type = "operations_officer"
    tier = "domain"
    instructions = _INSTRUCTIONS
    default_capabilities = [
        CapabilityDescriptor(can="ops_status", detail="Operational status analysis"),
        CapabilityDescriptor(can="ops_coordinate", detail="Cross-department coordination"),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="ops_status",
            params={"focus": "optional area to focus on"},
            description="Analyze current operational status — resource usage, coordination, efficiency",
        ),
        IntentDescriptor(
            name="ops_coordinate",
            params={"task": "task or initiative requiring cross-department coordination"},
            description="Plan cross-department coordination for a task or initiative",
        ),
    ]
    _handled_intents = {"ops_status", "ops_coordinate"}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("pool", "operations_officer")
        super().__init__(**kwargs)
        self._runtime = kwargs.get("runtime")
