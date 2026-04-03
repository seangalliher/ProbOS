"""Phase 3: Fleet organization — pool groups, scaler, federation (AD-517).

Registers pool groups, starts the pool scaler, and sets up federation
transport/bridge if enabled.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from probos.startup.results import FleetOrganizationResult
from probos.substrate.pool_group import PoolGroup

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.config import SystemConfig
    from probos.consensus.escalation import EscalationManager
    from probos.consensus.trust import TrustNetwork
    from probos.mesh.intent import IntentBus
    from probos.substrate.pool import ResourcePool
    from probos.substrate.pool_group import PoolGroupRegistry

logger = logging.getLogger(__name__)


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
) -> FleetOrganizationResult:
    """Register pool groups, start scaler, set up federation."""
    logger.info("Startup [fleet_organization]: starting")

    # Register pool groups (crew teams) — AD-291
    pool_groups.register(PoolGroup(
        name="core",
        display_name="Core Systems",
        pool_names={"system", "filesystem", "filesystem_writers", "directory", "search", "shell", "http", "introspect", "medical_vitals", "red_team", "system_qa"},
        exclude_from_scaler=True,
    ))

    if config.utility_agents.enabled:
        pool_groups.register(PoolGroup(
            name="utility",
            display_name="Utility Agents",
            pool_names={"web_search", "page_reader", "weather", "news", "translator", "summarizer", "calculator", "todo_manager", "note_taker", "scheduler"},
        ))

    if config.medical.enabled:
        pool_groups.register(PoolGroup(
            name="medical",
            display_name="Medical",
            pool_names={"medical_diagnostician", "medical_surgeon", "medical_pharmacist", "medical_pathologist"},
            exclude_from_scaler=True,
        ))

    if config.self_mod.enabled:
        sm_pools = {"skills"}
        pool_groups.register(PoolGroup(
            name="self_mod",
            display_name="Self-Modification",
            pool_names=sm_pools,
            exclude_from_scaler=True,
        ))

    # Security pool group (AD-398: cognitive security officer)
    pool_groups.register(PoolGroup(
        name="security",
        display_name="Security",
        pool_names={"security_officer"},
        exclude_from_scaler=True,
    ))

    # Engineering pool group (AD-302, AD-398: add engineering_officer)
    pool_groups.register(PoolGroup(
        name="engineering",
        display_name="Engineering",
        pool_names={"builder", "engineering_officer"},
        exclude_from_scaler=True,
    ))

    # Science pool group (AD-307)
    pool_groups.register(PoolGroup(
        name="science",
        display_name="Science",
        pool_names={"architect", "scout", "science_data_analyst", "science_systems_analyst", "science_research_specialist"},
        exclude_from_scaler=True,
    ))

    # Operations pool group (AD-398)
    pool_groups.register(PoolGroup(
        name="operations",
        display_name="Operations",
        pool_names={"operations_officer"},
        exclude_from_scaler=True,
    ))

    # Bridge pool group (BF-015: Counselor was ungrouped)
    pool_groups.register(PoolGroup(
        name="bridge",
        display_name="Bridge",
        pool_names={"counselor"},
        exclude_from_scaler=True,
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

    # Start federation if enabled
    federation_bridge = None
    federation_transport = None
    if config.federation.enabled:
        from probos.federation import FederationRouter, FederationBridge
        from probos.federation.mock_transport import MockFederationTransport, MockTransportBus

        # Use real transport if pyzmq available, else skip
        transport = None
        try:
            from probos.federation.transport import FederationTransport

            transport = FederationTransport(
                node_id=config.federation.node_id,
                bind_address=config.federation.bind_address,
                peers=config.federation.peers,
            )
            await transport.start()
        except ImportError:
            logger.warning("pyzmq not available; federation transport disabled")
        except Exception as e:
            logger.warning("Federation transport failed to start: %s", e)

        if transport is not None:
            router = FederationRouter()
            validate_fn = (
                validate_remote_result_fn
                if config.federation.validate_remote_results
                else None
            )
            bridge = FederationBridge(
                node_id=config.federation.node_id,
                transport=transport,
                router=router,
                intent_bus=intent_bus,
                config=config.federation,
                self_model_fn=build_self_model_fn,
                validate_fn=validate_fn,
            )
            await bridge.start()
            # PATCH(AD-517): Wire federation function into intent bus
            intent_bus._federation_fn = bridge.forward_intent
            federation_bridge = bridge
            federation_transport = transport
            logger.info("Federation started: node=%s", config.federation.node_id)

    logger.info("Startup [fleet_organization]: complete")
    return FleetOrganizationResult(
        pool_scaler=pool_scaler,
        federation_bridge=federation_bridge,
        federation_transport=federation_transport,
    )
