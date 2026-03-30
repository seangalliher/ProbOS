"""Phase 2: Agent fleet creation (AD-517).

Creates agent pools, builds the codebase index, refreshes intent
descriptors, wires strategy advisors, and spawns red-team agents.

Note: The AgentOnboardingService is created in start() *before* this
phase runs, because wire_agent (called during pool creation) depends
on self.onboarding being set.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from probos.startup.results import AgentFleetResult
from probos.substrate.identity import generate_pool_ids

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.config import SystemConfig
    from probos.cognitive.decomposer import IntentDecomposer
    from probos.substrate.pool import ResourcePool

logger = logging.getLogger(__name__)


async def create_agent_fleet(
    *,
    config: "SystemConfig",
    pools: dict[str, "ResourcePool"],
    llm_client: "BaseLLMClient",
    decomposer: "IntentDecomposer",
    strategy_advisor: Any,
    runtime: Any,  # ProbOSRuntime reference for create_pool
    create_pool_fn: Callable[..., Any],
    spawn_red_team_fn: Callable[..., Any],
    collect_intent_descriptors_fn: Callable[[], list[Any]],
) -> AgentFleetResult:
    """Create agent pools, build codebase index, wire strategy advisors."""
    logger.info("Startup [agent_fleet]: starting")

    # Start default pools (Phase 14c: deterministic agent IDs)
    _builtin_pools = [
        ("system", "system_heartbeat", 2),
        ("filesystem", "file_reader", 3),
        ("filesystem_writers", "file_writer", 3),
        ("directory", "directory_list", 3),
        ("search", "file_search", 3),
        ("shell", "shell_command", 3),
        ("http", "http_fetch", 3),
    ]
    for pool_name, agent_type, size in _builtin_pools:
        ids = generate_pool_ids(agent_type, pool_name, size)
        await create_pool_fn(pool_name, agent_type, target_size=size, agent_ids=ids)

    # Introspect pool (needs runtime kwarg)
    ids = generate_pool_ids("introspect", "introspect", 2)
    await create_pool_fn("introspect", "introspect", target_size=2, agent_ids=ids, runtime=runtime)

    # Bundled CognitiveAgent pools (Phase 22, AD-252)
    if config.utility_agents.enabled:
        _utility_pools = [
            ("web_search", "web_search", 2),
            ("page_reader", "page_reader", 2),
            ("weather", "weather", 2),
            ("news", "news", 2),
            ("translator", "translator", 2),
            ("summarizer", "summarizer", 2),
            ("calculator", "calculator", 2),
            ("todo_manager", "todo_manager", 2),
            ("note_taker", "note_taker", 2),
            ("scheduler", "scheduler", 2),
        ]
        for pool_name, agent_type, size in _utility_pools:
            ids = generate_pool_ids(agent_type, pool_name, size)
            await create_pool_fn(
                pool_name, agent_type, target_size=size,
                agent_ids=ids, llm_client=llm_client, runtime=runtime,
            )

    # Engineering team — Builder Agent (AD-302)
    if config.utility_agents.enabled:
        ids = generate_pool_ids("builder", "builder", 1)
        await create_pool_fn(
            "builder", "builder", target_size=1,
            agent_ids=ids, llm_client=llm_client, runtime=runtime,
        )

    # Science team — Architect Agent (AD-307)
    if config.utility_agents.enabled:
        ids = generate_pool_ids("architect", "architect", 1)
        await create_pool_fn(
            "architect", "architect", target_size=1,
            agent_ids=ids, llm_client=llm_client, runtime=runtime,
        )

    # Science team — Scout Agent (AD-394)
    if config.utility_agents.enabled:
        ids = generate_pool_ids("scout", "scout", 1)
        await create_pool_fn(
            "scout", "scout", target_size=1,
            agent_ids=ids, llm_client=llm_client, runtime=runtime,
        )

    # Bridge crew — Counselor (AD-398)
    if config.utility_agents.enabled:
        ids = generate_pool_ids("counselor", "counselor", 1)
        await create_pool_fn(
            "counselor", "counselor", target_size=1,
            agent_ids=ids, llm_client=llm_client, runtime=runtime,
        )

    # Security team — Security Officer (AD-398)
    if config.utility_agents.enabled:
        ids = generate_pool_ids("security_officer", "security_officer", 1)
        await create_pool_fn(
            "security_officer", "security_officer", target_size=1,
            agent_ids=ids, llm_client=llm_client, runtime=runtime,
        )

    # Operations team — Operations Officer (AD-398)
    if config.utility_agents.enabled:
        ids = generate_pool_ids("operations_officer", "operations_officer", 1)
        await create_pool_fn(
            "operations_officer", "operations_officer", target_size=1,
            agent_ids=ids, llm_client=llm_client, runtime=runtime,
        )

    # Engineering team — Engineering Officer (AD-398)
    if config.utility_agents.enabled:
        ids = generate_pool_ids("engineering_officer", "engineering_officer", 1)
        await create_pool_fn(
            "engineering_officer", "engineering_officer", target_size=1,
            agent_ids=ids, llm_client=llm_client, runtime=runtime,
        )

    # Build CodebaseIndex — ship's library, available to all agents (AD-297)
    from probos.cognitive.codebase_index import CodebaseIndex

    codebase_index = CodebaseIndex(source_root=Path(__file__).resolve().parent.parent)
    codebase_index.build()

    # Medical team pool (AD-290)
    if config.medical.enabled:
        med_cfg = config.medical

        # Create vitals monitor pool entry (HeartbeatAgent — no LLM)
        ids = generate_pool_ids("vitals_monitor", "medical_vitals", 1)
        await create_pool_fn(
            "medical_vitals", "vitals_monitor", target_size=1,
            agent_ids=ids, runtime=runtime,
            window_size=med_cfg.vitals_window_size,
            pool_health_min=med_cfg.pool_health_min,
            trust_floor=med_cfg.trust_floor,
            health_floor=med_cfg.health_floor,
            max_trust_outliers=med_cfg.max_trust_outliers,
        )

        # CognitiveAgent medical agents — all share "medical" pool
        _medical_cognitive = [
            ("diagnostician", "diagnostician"),
            ("surgeon", "surgeon"),
            ("pharmacist", "pharmacist"),
            ("pathologist", "pathologist"),
        ]
        for agent_type_name, pool_suffix in _medical_cognitive:
            ids = generate_pool_ids(agent_type_name, f"medical_{pool_suffix}", 1)
            await create_pool_fn(
                f"medical_{pool_suffix}", agent_type_name, target_size=1,
                agent_ids=ids, llm_client=llm_client, runtime=runtime,
            )

        # Register codebase_knowledge skill on CognitiveAgent medical agents
        from probos.cognitive.codebase_skill import create_codebase_skill

        codebase_skill = create_codebase_skill(codebase_index)
        for pool_name in ["medical_pathologist"]:
            pool = pools.get(pool_name)
            if pool:
                for agent in pool.healthy_agents:
                    if hasattr(agent, "add_skill"):
                        agent.add_skill(codebase_skill)

    # Attach codebase_knowledge skill to architect pool (AD-307)
    if config.utility_agents.enabled:
        from probos.cognitive.codebase_skill import create_codebase_skill as _create_cb_skill

        _cb_skill = _create_cb_skill(codebase_index)
        pool = pools.get("architect")
        if pool:
            for agent in pool.healthy_agents:
                if hasattr(agent, "add_skill"):
                    agent.add_skill(_cb_skill)

    # Refresh decomposer with intent descriptors from all registered templates
    decomposer.refresh_descriptors(collect_intent_descriptors_fn())

    # Wire StrategyAdvisor on all CognitiveAgent instances (AD-384)
    if strategy_advisor:
        from probos.cognitive.cognitive_agent import CognitiveAgent as _CA

        for pool in pools.values():
            for agent in pool.healthy_agents:
                if isinstance(agent, _CA) and hasattr(agent, "set_strategy_advisor"):
                    agent.set_strategy_advisor(strategy_advisor)

    # Spawn red team agents (populates runtime._red_team_agents in-place)
    await spawn_red_team_fn(config.consensus.red_team_pool_size)

    logger.info("Startup [agent_fleet]: complete")
    return AgentFleetResult(
        onboarding_service=None,  # created in start() before this phase
        codebase_index=codebase_index,
        red_team_agents=[],  # populated directly on runtime by spawn_red_team_fn
    )
