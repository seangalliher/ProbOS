"""AD-480c: AgentCard — A2A 0.2.0 spec serializer.

Read at /.well-known/agent.json by A2A clients to discover this ship's
capabilities. Reads vessel_name + ship_did from AgentIdentityRegistry per
the AD-441 / AD-499 connection at roadmap.md:7013.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


@dataclass
class AgentCapabilities:
    streaming: bool = False              # 480j parks SSE
    pushNotifications: bool = False      # 480m parks push
    stateTransitionHistory: bool = False


@dataclass
class AgentProvider:
    organization: str = ""
    url: str = ""


@dataclass
class AgentSkill:
    id: str
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    inputModes: list[str] = field(default_factory=lambda: ["text"])
    outputModes: list[str] = field(default_factory=lambda: ["text"])


@dataclass
class AgentCard:
    name: str
    description: str
    url: str
    version: str
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = field(default_factory=list)
    defaultInputModes: list[str] = field(default_factory=lambda: ["text"])
    defaultOutputModes: list[str] = field(default_factory=lambda: ["text"])
    provider: AgentProvider | None = None

    def to_json_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "capabilities": {
                "streaming": self.capabilities.streaming,
                "pushNotifications": self.capabilities.pushNotifications,
                "stateTransitionHistory": self.capabilities.stateTransitionHistory,
            },
            "skills": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "tags": list(s.tags),
                    "examples": list(s.examples),
                    "inputModes": list(s.inputModes),
                    "outputModes": list(s.outputModes),
                }
                for s in self.skills
            ],
            "defaultInputModes": list(self.defaultInputModes),
            "defaultOutputModes": list(self.defaultOutputModes),
        }
        if self.provider is not None:
            d["provider"] = {
                "organization": self.provider.organization,
                "url": self.provider.url,
            }
        return d

    @classmethod
    def from_runtime(
        cls,
        runtime: "ProbOSRuntime",
        *,
        base_url: str = "",
        version: str = "0.1.0",
    ) -> "AgentCard":
        """Build an AgentCard from the runtime's live state."""
        # Vessel identity (AD-441 / AD-499 connection per roadmap.md:7013)
        vessel_name = "ProbOS"
        ship_did = ""
        if runtime.identity_registry is not None:
            cert = runtime.identity_registry.get_ship_certificate()
            if cert is not None:
                vessel_name = cert.vessel_name
                ship_did = cert.ship_did

        # Skills derived from registered IntentDescriptors
        skills: list[AgentSkill] = []
        try:
            descriptors = list(runtime.decomposer._intent_descriptors.values())
        except Exception:
            logger.warning(
                "AD-480c: decomposer descriptor read failed; AgentCard "
                "has empty skills list",
                exc_info=True,
            )
            descriptors = []

        for desc in descriptors:
            skills.append(
                AgentSkill(
                    id=desc.name,
                    name=desc.name,
                    description=desc.description,
                    tags=[desc.tier],
                )
            )

        provider = AgentProvider(organization=vessel_name, url=ship_did)

        return cls(
            name=vessel_name,
            description=f"ProbOS {vessel_name} (ship_did={ship_did})",
            url=base_url,
            version=version,
            skills=skills,
            provider=provider,
        )
