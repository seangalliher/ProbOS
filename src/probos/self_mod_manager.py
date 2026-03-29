"""AD-515: Self-modification manager extracted from ProbOSRuntime.

Handles hot-reload of patched agents and skills, designed agent lifecycle,
and execution context formatting for the self-mod pipeline.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.substrate.identity import generate_pool_ids

logger = logging.getLogger(__name__)


class SelfModManager:
    """Manages self-modification hot-reload and designed agent lifecycle."""

    def __init__(
        self,
        *,
        self_mod_pipeline: Any,
        knowledge_store: Any | None,
        trust_network: Any,
        intent_bus: Any,
        capability_registry: Any,
        registry: Any,
        pools: dict[str, Any],
        spawner: Any,
        decomposer: Any,
        feedback_engine: Any | None,
        llm_client: Any | None,
        event_emitter: Any,
        config: Any,
        semantic_layer: Any | None,
        collect_intent_descriptors_fn: Any,
        process_natural_language_fn: Any,
        add_skill_to_agents_fn: Any,
        register_agent_type_fn: Any,
        unregister_agent_type_fn: Any,
        create_pool_fn: Any,
        runtime: Any | None = None,
    ) -> None:
        self._self_mod_pipeline = self_mod_pipeline
        self._knowledge_store = knowledge_store
        self._trust_network = trust_network
        self._intent_bus = intent_bus
        self._capability_registry = capability_registry
        self._registry = registry
        self._pools = pools
        self._spawner = spawner
        self._decomposer = decomposer
        self._feedback_engine = feedback_engine
        self._llm_client = llm_client
        self._event_emitter = event_emitter
        self._config = config
        self._semantic_layer = semantic_layer
        self._collect_intent_descriptors_fn = collect_intent_descriptors_fn
        self._process_natural_language_fn = process_natural_language_fn
        self._add_skill_to_agents_fn = add_skill_to_agents_fn
        self._register_agent_type_fn = register_agent_type_fn
        self._unregister_agent_type_fn = unregister_agent_type_fn
        self._create_pool_fn = create_pool_fn
        self._runtime = runtime

        # These are set by runtime since they reference runtime state
        self._last_execution: dict[str, Any] | None = None
        self._last_execution_text: str | None = None

    async def apply_correction(
        self,
        correction: Any,
        patch_result: Any,
        original_record: Any,
    ) -> Any:
        """Hot-reload a patched self-mod'd agent into the runtime."""
        from probos.cognitive.agent_patcher import CorrectionResult

        strategy = original_record.strategy
        agent_type = original_record.agent_type

        try:
            if strategy == "skill":
                await self._apply_skill_correction(
                    correction, patch_result, original_record,
                )
            else:
                await self._apply_agent_correction(
                    correction, patch_result, original_record,
                )
        except Exception as exc:
            logger.warning("apply_correction failed: %s", exc)
            return CorrectionResult(
                success=False,
                agent_type=agent_type,
                strategy=strategy,
                changes_description=f"Hot-reload failed: {exc}",
            )

        # Update the record
        original_record.source_code = patch_result.patched_source
        original_record.status = "patched"

        # Refresh decomposer descriptors
        if self._decomposer:
            try:
                descriptors = self._collect_intent_descriptors_fn()
                self._decomposer.refresh_descriptors(descriptors)
            except Exception:
                logger.warning("Failed to refresh decomposer descriptors — self-modified agent may not be routable", exc_info=True)

        # Persist to knowledge store
        if self._knowledge_store:
            try:
                await self._knowledge_store.store_agent(
                    original_record, patch_result.patched_source,
                )
            except Exception:
                logger.warning("Failed to persist patched agent — may be lost on restart", exc_info=True)
        # Auto-index for semantic search (AD-243)
        if self._semantic_layer:
            try:
                await self._semantic_layer.index_agent(
                    agent_type=original_record.agent_type,
                    intent_name=original_record.intent_name,
                    description=original_record.intent_name,
                    strategy=original_record.strategy,
                    source_snippet=patch_result.patched_source[:200] if patch_result.patched_source else "",
                )
            except Exception:
                pass

        # Auto-retry the original request
        retry_result = None
        retried = False
        original_text = self._last_execution_text
        if original_text:
            try:
                retried = True
                retry_result = await self._process_natural_language_fn(
                    original_text, on_event=None,
                )
            except Exception as exc:
                retry_result = {"error": str(exc)}

        # Record correction feedback (AD-234)
        retry_success = bool(
            retried and retry_result and not retry_result.get("error")
        )
        if self._feedback_engine:
            try:
                await self._feedback_engine.apply_correction_feedback(
                    original_text=original_text or "",
                    correction=correction,
                    patch_result=patch_result,
                    retry_success=retry_success,
                )
            except Exception:
                pass

        return CorrectionResult(
            success=True,
            agent_type=agent_type,
            strategy=strategy,
            changes_description=patch_result.changes_description,
            retried=retried,
            retry_result=retry_result,
        )

    async def _apply_agent_correction(
        self,
        correction: Any,
        patch_result: Any,
        record: Any,
    ) -> None:
        """Hot-swap a patched agent class into the runtime."""
        agent_type = record.agent_type
        pool_name = f"designed_{agent_type}"
        new_class = patch_result.agent_class

        if new_class is None:
            raise ValueError("PatchResult has no agent_class")

        # Register the new class template
        if self._spawner and hasattr(self._spawner, "_templates"):
            self._spawner._templates[agent_type] = new_class

        # Re-create pool agents with the new class
        pool = self._pools.get(pool_name)
        if pool:
            for agent in list(pool.healthy_agents):
                aid = agent.id if hasattr(agent, "id") else str(agent)
                try:
                    new_agent = new_class(
                        pool=pool_name,
                        llm_client=self._llm_client,
                    )
                    new_agent._id = aid  # preserve agent identity
                    self._registry.register(new_agent)
                    self._intent_bus.subscribe(
                        aid, new_agent.handle_intent,
                        intent_names=[d.name for d in getattr(new_agent, "intent_descriptors", [])] or None,
                    )
                    if hasattr(new_agent, "capabilities") and new_agent.capabilities:
                        self._capability_registry.register(aid, new_agent.capabilities)
                except Exception as exc:
                    logger.warning("Failed to replace agent %s: %s", aid, exc)

    async def _apply_skill_correction(
        self,
        correction: Any,
        patch_result: Any,
        record: Any,
    ) -> None:
        """Hot-swap a patched skill handler."""
        from probos.types import IntentDescriptor, Skill

        intent_name = correction.target_intent or record.intent_name
        handler = patch_result.handler

        if handler is None:
            raise ValueError("PatchResult has no handler")

        # Build a replacement skill
        new_skill = Skill(
            name=intent_name,
            descriptor=IntentDescriptor(
                name=intent_name,
                description=correction.explanation or record.intent_name,
            ),
            source_code=patch_result.patched_source,
            handler=handler,
            created_at=time.time(),
            origin="patched",
        )

        # Find agents with the old skill and replace it
        if self._add_skill_to_agents_fn:
            self._add_skill_to_agents_fn(new_skill)

    def find_designed_record(self, agent_type: str) -> Any:
        """Find the most recent active DesignedAgentRecord for an agent type."""
        if not self._self_mod_pipeline:
            return None
        records = self._self_mod_pipeline._records
        # Search in reverse (most recent first)
        for record in reversed(records):
            if record.agent_type == agent_type and record.status in (
                "active", "patched",
            ):
                return record
        return None

    def was_last_execution_successful(self) -> bool:
        """Check whether the last execution had any failed nodes."""
        if not self._last_execution:
            return False
        dag = self._last_execution.get("dag")
        if dag is None:
            return True  # No DAG info — assume success
        nodes = getattr(dag, "nodes", [])
        if not nodes:
            return True
        return all(
            getattr(n, "status", "completed") == "completed"
            for n in nodes
        )

    def format_execution_context(self) -> str:
        """Format last execution results as context for AgentDesigner (AD-235)."""
        if not self._last_execution:
            return ""

        parts: list[str] = []
        original_text = self._last_execution_text or ""
        if original_text:
            parts.append(f"Prior user request: {original_text!r}")

        dag = self._last_execution.get("dag")
        if dag is not None:
            nodes = getattr(dag, "nodes", [])
            for node in nodes:
                intent = getattr(node, "intent", "?")
                status = getattr(node, "status", "?")
                params = getattr(node, "params", {})
                result = getattr(node, "result", None)
                result_summary = ""
                if isinstance(result, dict):
                    for k in ("output", "result", "agent_id"):
                        v = result.get(k)
                        if v is not None:
                            val = str(v)
                            if len(val) > 200:
                                val = val[:200] + "..."
                            result_summary += f", {k}={val!r}"
                parts.append(
                    f"  [intent: {intent}, params: {params}, status: {status}{result_summary}]"
                )

        return "\n".join(parts) if parts else ""

    async def register_designed_agent(self, agent_class: type) -> None:
        """Register a self-designed agent class. Wraps register_agent_type()."""
        agent_type = getattr(agent_class, "agent_type", "unknown")
        self._register_agent_type_fn(agent_type, agent_class)

    async def unregister_designed_agent(self, agent_type: str) -> None:
        """Rollback registration of a self-designed agent type (AD-368)."""
        self._unregister_agent_type_fn(agent_type)

    async def create_designed_pool(self, agent_type: str, pool_name: str, size: int = 1) -> None:
        """Create a pool for a self-designed agent type."""
        ids = generate_pool_ids(agent_type, pool_name, size)
        await self._create_pool_fn(
            pool_name, agent_type, target_size=size,
            agent_ids=ids, llm_client=self._llm_client, runtime=self._runtime,
        )

    async def set_probationary_trust(self, pool_name: str) -> None:
        """Set probationary trust for all agents in a designed pool."""
        pool = self._pools.get(pool_name)
        if not pool:
            return
        for agent in pool.healthy_agents:
            self._trust_network.create_with_prior(
                agent.id,
                alpha=self._config.self_mod.probationary_alpha,
                beta=self._config.self_mod.probationary_beta,
            )
