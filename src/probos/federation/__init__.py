"""Federation — multi-node communication layer for ProbOS."""

from probos.federation.mock_transport import MockFederationTransport, MockTransportBus
from probos.federation.nats_transport import NATSFederationTransport
from probos.federation.router import FederationRouter
from probos.federation.bridge import FederationBridge
from probos.federation.hebbian_map import FederationHebbianMap
from probos.federation.cluster_monitor import FederationClusterMonitor
from probos.federation.multicast_discovery import MulticastDiscovery

__all__ = [
    "MockFederationTransport",
    "MockTransportBus",
    "NATSFederationTransport",
    "FederationRouter",
    "FederationBridge",
    "FederationHebbianMap",
    "FederationClusterMonitor",
    "MulticastDiscovery",
]
