"""Federation — multi-node communication layer for ProbOS."""

from probos.federation.mock_transport import MockFederationTransport, MockTransportBus
from probos.federation.nats_transport import NATSFederationTransport
from probos.federation.router import FederationRouter
from probos.federation.bridge import FederationBridge

__all__ = [
    "MockFederationTransport",
    "MockTransportBus",
    "NATSFederationTransport",
    "FederationRouter",
    "FederationBridge",
]
