"""AD-512 v1: Discovery-Based Capability Building substrate.

Six capability primitives that future Holodeck consumers (AD-486 Birth
Chamber, AD-510 Team Simulations) wire together to drive experiential
learning — discovery scenarios, strength mapping, cross-functional
suggestion, growth mindset framing, capability confidence (Beta(α,β)),
and Vygotsky ZPD calibration. v1 is observational only.

No consumers in v1 — content delivery and Hebbian/episodic writes are
caller responsibilities. AD-486 / AD-510 will consume this substrate.
"""

from probos.crew_development.discovery.scenarios import (
    DiscoveryScenario,
    DiscoveryScenarioRegistry,
)
from probos.crew_development.discovery.strength_map import (
    StrengthMap,
    StrengthRecord,
)
from probos.crew_development.discovery.cross_functional import (
    CrossFunctionalSuggestion,
    suggest_routing,
)
from probos.crew_development.discovery.framing import (
    frame_as_discovery,
    frame_as_growth,
)
from probos.crew_development.discovery.confidence import (
    CapabilityConfidence,
    CapabilityConfidenceScorer,
)
from probos.crew_development.discovery.zpd import (
    ZPDBand,
    ZPDCalibrator,
)

__all__ = [
    "DiscoveryScenario",
    "DiscoveryScenarioRegistry",
    "StrengthMap",
    "StrengthRecord",
    "CrossFunctionalSuggestion",
    "suggest_routing",
    "frame_as_discovery",
    "frame_as_growth",
    "CapabilityConfidence",
    "CapabilityConfidenceScorer",
    "ZPDBand",
    "ZPDCalibrator",
]
