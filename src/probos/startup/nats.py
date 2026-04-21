"""NATS event bus initialization (AD-637a).

Runs in Phase 1b (infrastructure) — NATS must be available before
communication services start.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import SystemConfig
    from probos.mesh.nats_bus import NATSBus

logger = logging.getLogger(__name__)


async def init_nats(config: "SystemConfig") -> "NATSBus | None":
    """Initialize NATS bus if enabled.

    Returns NATSBus instance (connected or degraded) or None if disabled.
    """
    if not config.nats.enabled:
        logger.info("Startup [nats]: disabled")
        return None

    from probos.mesh.nats_bus import NATSBus

    logger.info("Startup [nats]: connecting to %s", config.nats.url)

    bus = NATSBus(
        url=config.nats.url,
        connect_timeout=config.nats.connect_timeout_seconds,
        max_reconnect_attempts=config.nats.max_reconnect_attempts,
        reconnect_time_wait=config.nats.reconnect_time_wait_seconds,
        drain_timeout=config.nats.drain_timeout_seconds,
        subject_prefix=config.nats.subject_prefix,
        jetstream_enabled=config.nats.jetstream_enabled,
    )

    await bus.start()

    if bus.connected:
        logger.info(
            "Startup [nats]: connected (JetStream=%s)",
            config.nats.jetstream_enabled,
        )
    else:
        logger.warning(
            "Startup [nats]: connection failed — system will operate without NATS. "
            "Install and start nats-server: https://docs.nats.io/running-a-nats-service/introduction/installation"
        )

    return bus
