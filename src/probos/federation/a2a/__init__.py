"""AD-480: A2A Federation Adapter -- ProbOS as A2A server + A2A client."""

from probos.federation.a2a.agent_card import (
    AgentCard,
    AgentCapabilities,
    AgentProvider,
    AgentSkill,
)
from probos.federation.a2a.client import A2AClient, A2AProtocolError
from probos.federation.a2a.server import FederationA2AServer

# A2A spec version we conform to.
A2A_PROTOCOL_VERSION = "0.2.0"

__all__ = [
    "AgentCard",
    "AgentCapabilities",
    "AgentProvider",
    "AgentSkill",
    "A2AClient",
    "A2AProtocolError",
    "A2A_PROTOCOL_VERSION",
    "FederationA2AServer",
]
