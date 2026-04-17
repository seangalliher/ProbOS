"""AD-640: Tiered Trust Initialization.

Resolves the trust tier for an agent based on pool name and callsign,
then initializes their trust record with the appropriate Beta prior.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Protocol

from probos.config import TieredTrustConfig

logger = logging.getLogger(__name__)


class TrustTier(str, Enum):
    """Trust initialization tiers."""
    BRIDGE = "bridge"
    CHIEF = "chief"
    CREW = "crew"
    # PROBATIONARY is handled by self_mod_manager.py (existing)


class TrustServiceProtocol(Protocol):
    """Narrow interface for trust initialization."""

    def create_with_prior(self, agent_id: str, alpha: float, beta: float) -> None: ...
    def get_or_create(self, agent_id: str) -> object: ...


def resolve_tier(
    pool: str,
    callsign: str,
    config: TieredTrustConfig,
) -> TrustTier:
    """Determine which trust tier an agent belongs to.

    Resolution order:
    1. Bridge pools (counselor) -> BRIDGE
    2. Bridge callsigns (Meridian) -> BRIDGE
    3. Chief callsigns (Bones, LaForge, etc.) -> CHIEF
    4. Everything else -> CREW
    """
    if pool in config.bridge_pools:
        return TrustTier.BRIDGE
    if callsign in config.bridge_callsigns:
        return TrustTier.BRIDGE
    if callsign in config.chief_callsigns:
        return TrustTier.CHIEF
    return TrustTier.CREW


def initialize_trust(
    agent_id: str,
    pool: str,
    callsign: str,
    trust_network: TrustServiceProtocol,
    config: TieredTrustConfig,
    consensus_alpha: float = 2.0,
    consensus_beta: float = 2.0,
) -> TrustTier:
    """Initialize an agent's trust record based on their tier.

    Returns the resolved tier for logging/boot camp integration.
    """
    if not config.enabled:
        trust_network.get_or_create(agent_id)
        return TrustTier.CREW

    tier = resolve_tier(pool, callsign, config)

    if tier == TrustTier.BRIDGE:
        trust_network.create_with_prior(agent_id, config.bridge_alpha, config.bridge_beta)
        logger.info("AD-640: %s (%s) -> BRIDGE tier (a=%.1f, b=%.1f)",
                     callsign, agent_id, config.bridge_alpha, config.bridge_beta)
    elif tier == TrustTier.CHIEF:
        trust_network.create_with_prior(agent_id, config.chief_alpha, config.chief_beta)
        logger.info("AD-640: %s (%s) -> CHIEF tier (a=%.1f, b=%.1f)",
                     callsign, agent_id, config.chief_alpha, config.chief_beta)
    else:
        trust_network.create_with_prior(agent_id, consensus_alpha, consensus_beta)
        logger.debug("AD-640: %s (%s) -> CREW tier (default)", callsign, agent_id)

    return tier
