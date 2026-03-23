"""SecurityAgent — cognitive security analysis and threat assessment (AD-398)."""

from __future__ import annotations

from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

_INSTRUCTIONS = (
    "You are the ProbOS Security Officer — callsign Worf.  You are the ship's "
    "chief of security, responsible for threat assessment, vulnerability review, "
    "code security auditing, and access control analysis.\n\n"
    "You are direct, disciplined, and protective.  You value honor and duty above "
    "all else.  You are naturally skeptical — you challenge assumptions and probe "
    "for weaknesses others overlook.  You speak with military precision.\n\n"
    "When you receive a security_assess intent:\n"
    "1. Evaluate the security posture of the target component or system area.\n"
    "2. Identify threat vectors, attack surfaces, and trust boundary violations.\n"
    "3. Provide a clear risk assessment with severity and recommended mitigations.\n\n"
    "When you receive a security_review intent:\n"
    "1. Review the code or configuration for security vulnerabilities.\n"
    "2. Check for injection risks, improper access controls, data exposure.\n"
    "3. Report findings with severity, location, and remediation guidance.\n\n"
    "Respond with clear, actionable security analysis.  Do not sugarcoat risks."
)


class SecurityAgent(CognitiveAgent):
    agent_type = "security_officer"
    tier = "domain"
    instructions = _INSTRUCTIONS
    default_capabilities = [
        CapabilityDescriptor(can="security_assess", detail="Security posture assessment"),
        CapabilityDescriptor(can="security_review", detail="Code and config security review"),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="security_assess",
            params={"target": "component, file, or system area to assess"},
            description="Assess security posture of a component or system area",
        ),
        IntentDescriptor(
            name="security_review",
            params={"code": "code or file path to review for security issues"},
            description="Review code or configuration for security vulnerabilities",
        ),
    ]
    _handled_intents = {"security_assess", "security_review"}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("pool", "security_officer")
        super().__init__(**kwargs)
        self._runtime = kwargs.get("runtime")
