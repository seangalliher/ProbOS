"""Phase 3: Fleet organization — pool groups, scaler, federation (AD-517).

Registers pool groups, starts the pool scaler, and sets up federation
transport/bridge if enabled.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from probos.startup.results import FleetOrganizationResult
from probos.substrate.pool_group import PoolGroup

if TYPE_CHECKING:
    from pathlib import Path

    from probos.cognitive.llm_client import BaseLLMClient
    from probos.config import SystemConfig
    from probos.consensus.escalation import EscalationManager
    from probos.consensus.trust import TrustNetwork
    from probos.federation.relay import FederationRelayTopic
    from probos.mesh.intent import IntentBus
    from probos.substrate.pool import ResourcePool
    from probos.substrate.pool_group import PoolGroupRegistry

logger = logging.getLogger(__name__)


def _envelope_transport(
    config: "SystemConfig", transport: Any, identity_key_binding: Any | None, data_dir: "Path | None",
    identity_registry: Any | None = None,
) -> Any:
    """AD-1197/AD-1198: the transport wrapped for signed envelopes (and peer admission when armed); the transport itself when off."""
    if config.federation.envelope_signing_enabled is not True:  # AD-1197 off: the transport itself
        return transport
    if data_dir is None:
        raise ValueError("federation envelope signing needs a data directory for its replay store")
    from probos.federation.signed_transport import build_signed_transport

    admission = None
    ledger = None
    if config.federation.peer_admission_enabled is True:  # AD-1198 armed: configured, pinned peers only
        from probos.federation.admission import PeerAdmission

        admission = PeerAdmission.from_config(config.federation)
        if identity_registry is not None:  # AD-1198 A-1 at start a held history's pin may be judged on identity.db's chain
            from functools import partial

            from probos.federation.continuity import stored_key_history

            ledger = partial(stored_key_history, identity_registry)
    return build_signed_transport(
        transport, policy=config.federation.envelope_policy, key_binding=identity_key_binding, data_dir=data_dir,
        admission=admission, ledger=ledger,
    )


_UNPUBLISHED_STOP_TASK_NAME = "ad1198-unpublished-federation-stop"


async def _stop_unpublished_federation(exchange: Any, bridge: Any, transport: Any) -> None:
    """AD-1198 A-1/A-2: stop the federation a failed fleet organization built but never handed to the runtime, whose
    rollback cannot reach it -- the identity exchange, the bridge, then the transport, as shutdown orders them.

    The stops run in a task of their own (the BF-882 rollback pattern, ``startup/rollback.py``): the caller waits for it
    under ``asyncio.shield``, so a cancellation of the caller does not interrupt them; such a cancellation is raised once
    they have finished, and otherwise this returns and the caller re-raises its own error. ``_stop_each`` catches every
    ``Exception`` itself, so the task can only end cancelled, which is logged.
    """
    logger.warning(
        "AD-1198: fleet organization failed after its federation transport was built; stopping the federation it "
        "built before the error propagates"
    )
    current = asyncio.current_task()
    cancelling_at_entry = current.cancelling() if current is not None else 0
    stopping = asyncio.create_task(_stop_each(exchange, bridge, transport), name=_UNPUBLISHED_STOP_TASK_NAME)
    outer: asyncio.CancelledError | None = None
    while not stopping.done():
        try:
            await asyncio.shield(stopping)  # AD-1198 A-2 a cancellation of the caller does not interrupt the stops
        except asyncio.CancelledError as cancelled:
            if outer is None and current is not None and current.cancelling() > cancelling_at_entry:  # AD-1198 A-2 the caller was cancelled: keep waiting, raise it afterwards
                outer = cancelled
    if stopping.cancelled():
        logger.warning(
            "AD-1198: the cleanup of a failed fleet organization was itself cancelled; a component it could not stop "
            "may stay running until the process exits"
        )
    if outer is not None:
        raise outer  # AD-1198 A-2 a cancellation that arrived during the cleanup is raised once it has finished


async def _stop_each(exchange: Any, bridge: Any, transport: Any) -> None:
    """The identity exchange, the bridge, then the transport, each that exists: a stop that fails or ends cancelled is
    logged and the next still runs, and such a cancellation is raised once every stop has run."""
    interrupted: asyncio.CancelledError | None = None
    for label, component in (("identity exchange", exchange), ("bridge", bridge), ("transport", transport)):
        if component is None:
            continue
        try:
            await component.stop()
        except asyncio.CancelledError as cancelled:  # AD-1198 A-2 a stop that ends cancelled does not skip the next
            interrupted = interrupted or cancelled
            logger.warning(
                "AD-1198: the federation %s of a failed fleet organization was cancelled while it stopped; continuing",
                label,
            )
        except Exception as exc:  # noqa: BLE001 -- rollback degrades: the original error propagates
            logger.warning(
                "AD-1198: the federation %s of a failed fleet organization did not stop cleanly (%s); continuing",
                label, type(exc).__name__,
            )
    if interrupted is not None:
        raise interrupted


async def organize_fleet(
    *,
    config: "SystemConfig",
    pools: dict[str, "ResourcePool"],
    pool_groups: "PoolGroupRegistry",
    escalation_manager: "EscalationManager",
    intent_bus: "IntentBus",
    trust_network: "TrustNetwork",
    llm_client: "BaseLLMClient",
    build_pool_intent_map_fn: Callable[[], dict[str, list[str]]],
    find_consensus_pools_fn: Callable[[], set[str]],
    build_self_model_fn: Callable[..., Any],
    validate_remote_result_fn: Callable[..., Any] | None,
    attachment_resolver_fn: (
        Callable[[dict[str, Any], str], Awaitable[int]] | None
    ),
    relay_topics: tuple["FederationRelayTopic", ...] = (),
    nats_bus: Any | None = None,
    identity_key_binding: Any | None = None,
    data_dir: "Path | None" = None,
    identity_registry: Any | None = None,
) -> FleetOrganizationResult:
    """Register pool groups, start scaler, set up federation."""
    logger.info("Startup [fleet_organization]: starting")

    # Register pool groups (crew teams) — AD-291
    pool_groups.register(PoolGroup(
        name="core",
        display_name="Core Systems",
        pool_names={"system", "filesystem", "filesystem_writers", "directory", "search", "code_search", "code_runner", "shell", "http", "introspect", "medical_vitals", "red_team", "system_qa"},
        exclude_from_scaler=True,
        startup_phase=1,  # AD-447: infrastructure first
    ))

    if config.utility_agents.enabled:
        pool_groups.register(PoolGroup(
            name="utility",
            display_name="Utility Agents",
            pool_names={"web_search", "page_reader", "weather", "news", "translator", "summarizer", "calculator", "todo_manager", "note_taker", "scheduler"},
            startup_phase=4,
        ))

    if config.medical.enabled:
        pool_groups.register(PoolGroup(
            name="medical",
            display_name="Medical",
            pool_names={"medical_diagnostician", "medical_surgeon", "medical_pharmacist", "medical_pathologist"},
            exclude_from_scaler=True,
            startup_phase=2,
        ))

    if config.self_mod.enabled:
        sm_pools = {"skills"}
        pool_groups.register(PoolGroup(
            name="self_mod",
            display_name="Self-Modification",
            pool_names=sm_pools,
            exclude_from_scaler=True,
            startup_phase=3,
        ))

    # Security pool group (AD-398: cognitive security officer)
    pool_groups.register(PoolGroup(
        name="security",
        display_name="Security",
        pool_names={"security_officer"},
        exclude_from_scaler=True,
        startup_phase=2,
    ))

    # Engineering pool group (AD-302, AD-398: add engineering_officer)
    pool_groups.register(PoolGroup(
        name="engineering",
        display_name="Engineering",
        pool_names={"builder", "engineering_officer"},
        exclude_from_scaler=True,
        startup_phase=2,
    ))

    # Science pool group (AD-307)
    pool_groups.register(PoolGroup(
        name="science",
        display_name="Science",
        pool_names={"architect", "scout", "science_data_analyst", "science_systems_analyst", "science_research_specialist"},
        exclude_from_scaler=True,
        startup_phase=3,
    ))

    # Operations pool group (AD-398)
    pool_groups.register(PoolGroup(
        name="operations",
        display_name="Operations",
        pool_names={"operations_officer", "training_officer"},
        exclude_from_scaler=True,
        startup_phase=2,
    ))

    # Bridge pool group (BF-015: Counselor was ungrouped; AD-766: Yeoman joins the Bridge)
    pool_groups.register(PoolGroup(
        name="bridge",
        display_name="Bridge",
        pool_names={"counselor", "yeoman"},
        exclude_from_scaler=True,
        startup_phase=1,  # AD-447: bridge is infrastructure
    ))

    # Start pool scaler if scaling is enabled
    pool_scaler = None
    if config.scaling.enabled:
        from probos.substrate.scaler import PoolScaler

        pool_intent_map = build_pool_intent_map_fn()
        consensus_pools = find_consensus_pools_fn()
        pool_scaler = PoolScaler(
            pools=pools,
            intent_bus=intent_bus,
            pool_config=config.pools,
            scaling_config=config.scaling,
            pool_intent_map=pool_intent_map,
            excluded_pools=pool_groups.excluded_pools(),
            trust_network=trust_network,
            consensus_pools=consensus_pools,
            consensus_min_agents=config.consensus.min_votes,
        )
        await pool_scaler.start()

        # PATCH(AD-517): Wire surge function into escalation manager
        escalation_manager._surge_fn = pool_scaler.request_surge

    # Start federation if enabled (AD-637e: NATS-first, ZeroMQ fallback)
    federation_bridge = None
    federation_transport = None
    federation_peer_requests = None
    identity_exchange = None
    if config.federation.enabled:
        from probos.federation import FederationRouter, FederationBridge

        peer_node_ids = [p.node_id for p in config.federation.peers]
        transport = None

        # Try NATS transport first (AD-637e)
        if nats_bus is not None and nats_bus.connected:
            try:
                from probos.federation.nats_transport import NATSFederationTransport

                transport = _envelope_transport(
                    config,
                    NATSFederationTransport(
                        node_id=config.federation.node_id,
                        nats_bus=nats_bus,
                        peer_node_ids=peer_node_ids,
                    ),
                    identity_key_binding,
                    data_dir,
                    identity_registry,  # AD-1198 A-1 the NATS transport's guard may judge a held pin on identity.db's chain
                )
                await transport.start()
                # AD-479f: TLS pass-through surface — NATSBus consumes config.tls
                # at start. v1 logs whether TLS is requested for observability;
                # actual TLS context is configured on NATSBus during AD-637a startup.
                if config.federation.tls.enabled:
                    logger.info(
                        "AD-479f: Federation TLS requested (NATS path); cert_file=%s ca_file=%s verify_peer=%s",
                        config.federation.tls.cert_file,
                        config.federation.tls.ca_file,
                        config.federation.tls.verify_peer,
                    )
                logger.info("AD-637e: Federation using NATS transport")
            except Exception as e:
                logger.warning("AD-637e: NATS federation transport failed, falling back to ZeroMQ: %s", e)
                transport = None

        # ZeroMQ fallback
        if transport is None:
            try:
                from probos.federation.transport import FederationTransport

                transport = _envelope_transport(
                    config,
                    FederationTransport(
                        node_id=config.federation.node_id,
                        bind_address=config.federation.bind_address,
                        peers=config.federation.peers,
                        harden_routing=config.federation.peer_admission_enabled is True,  # AD-1198 hardened routing when admission is armed
                    ),
                    identity_key_binding,
                    data_dir,
                    identity_registry,  # AD-1198 A-1 the ZeroMQ transport's guard may judge a held pin on identity.db's chain
                )
                await transport.start()
            except ImportError:
                logger.warning("pyzmq not available; federation transport disabled")
            except Exception as e:
                logger.warning("Federation transport failed to start: %s", e)

        if transport is not None:
            bridge = None
            try:
                router = FederationRouter()
                validate_fn = (
                    validate_remote_result_fn
                    if config.federation.validate_remote_results
                    else None
                )
                if config.federation.peer_admission_enabled is True and identity_registry is not None:  # AD-1198 slice 2a armed: the identity exchange answers chain and transfer requests
                    from probos.federation.admission import PeerAdmission
                    from probos.federation.continuity import IdentityExchange

                    identity_exchange = IdentityExchange(
                        node_id=config.federation.node_id, registry=identity_registry, seam=transport.chain_seam,
                        admission=PeerAdmission.from_config(config.federation),
                        timeout_ms=config.federation.forward_timeout_ms,
                    )
                    transport.chain_seam.on_history_gap(identity_exchange.history_gap)  # AD-1198 a key history gap asks for a resync
                bridge = FederationBridge(
                    node_id=config.federation.node_id,
                    transport=transport,
                    router=router,
                    intent_bus=intent_bus,
                    config=config.federation,
                    self_model_fn=build_self_model_fn,
                    validate_fn=validate_fn,
                    attachment_resolver=attachment_resolver_fn,
                    relay_topics=relay_topics,
                    identity_exchange=identity_exchange,  # AD-1198 None unless peer admission is armed: the bridge answers as before
                )
                await bridge.start()
                # PATCH(AD-517): Wire federation function into intent bus
                intent_bus.set_federation_handler(bridge.forward_intent)
                federation_bridge = bridge
                federation_transport = transport
                if config.federation.peer_admission_enabled is True:  # AD-1198 signed peer HTTP requests over the armed seam
                    from probos.federation.peer_requests import PeerRequests

                    federation_peer_requests = PeerRequests(transport.peer_request_seam)
            except BaseException:  # AD-1198 A-1 what the runtime was never handed must not outlive a failed organization
                await _stop_unpublished_federation(identity_exchange, bridge, transport)
                raise
            logger.info("Federation started: node=%s", config.federation.node_id)

    logger.info("Startup [fleet_organization]: complete")
    return FleetOrganizationResult(
        pool_scaler=pool_scaler,
        federation_bridge=federation_bridge,
        federation_transport=federation_transport,
        federation_peer_requests=federation_peer_requests,
        federation_identity_exchange=identity_exchange,
    )
