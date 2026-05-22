"""Phase 1: Infrastructure boot (AD-517).

Starts core infrastructure services and creates the identity registry.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from probos.startup.results import InfrastructureResult

if TYPE_CHECKING:
    from probos.config import SystemConfig
    from probos.consensus.trust import TrustNetwork
    from probos.mesh.gossip import GossipProtocol
    from probos.mesh.routing import HebbianRouter
    from probos.mesh.signal import SignalManager
    from probos.substrate.event_log import EventLog

logger = logging.getLogger(__name__)


async def boot_infrastructure(
    event_log: "EventLog",
    hebbian_router: "HebbianRouter",
    signal_manager: "SignalManager",
    gossip: "GossipProtocol",
    trust_network: "TrustNetwork",
    data_dir: Path,
    config: "SystemConfig",
    event_log_prune_loop_fn: Callable[[], asyncio.Future[None]],
    *,
    background_register: Callable[[asyncio.Task], None] | None = None,
) -> InfrastructureResult:
    """Start core infrastructure services and create the identity registry.

    Parameters
    ----------
    event_log_prune_loop_fn:
        Coroutine function to schedule as a background prune task
        (``runtime._event_log_prune_loop``).
    background_register:
        AD-824: optional callable that registers a task on the runtime's
        ``_background_tasks`` registry so the shutdown sweep can cancel
        it before the AD-820 clean-shutdown marker is written.
    """
    logger.info("Startup [infrastructure]: starting")

    # Start infrastructure
    data_dir.mkdir(parents=True, exist_ok=True)
    await event_log.start()
    event_prune_task = asyncio.create_task(
        event_log_prune_loop_fn(), name="event-log-prune-loop"
    )
    if background_register is not None:
        background_register(event_prune_task)
    await hebbian_router.start()
    await signal_manager.start()
    await gossip.start()
    await trust_network.start()

    # --- Sovereign Agent Identity (AD-441) ---
    from probos.identity import AgentIdentityRegistry

    identity_registry = AgentIdentityRegistry(data_dir=data_dir)
    await identity_registry.start()
    logger.info("identity registry started")

    logger.info("Startup [infrastructure]: complete")
    return InfrastructureResult(
        identity_registry=identity_registry,
        event_prune_task=event_prune_task,
    )
