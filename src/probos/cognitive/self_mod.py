"""SelfModificationPipeline — orchestrates agent design, validation, and registration."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.cognitive.agent_designer import AgentDesigner
    from probos.cognitive.behavioral_monitor import BehavioralMonitor
    from probos.cognitive.code_validator import CodeValidator
    from probos.cognitive.sandbox import SandboxRunner
    from probos.config import SelfModConfig

logger = logging.getLogger(__name__)


@dataclass
class DesignedAgentRecord:
    """Record of a self-created agent type."""

    intent_name: str
    agent_type: str
    class_name: str
    source_code: str
    created_at: float
    sandbox_time_ms: float = 0.0
    pool_name: str = ""
    status: str = "active"  # "active", "removed", "failed_validation", "rejected_by_user"


class SelfModificationPipeline:
    """Orchestrates the full self-modification flow.

    Flow:
    1. Check config: is self_mod enabled? Under max_designed_agents?
    2. Ask user for approval to design an agent (if require_user_approval)
    3. Call AgentDesigner to generate code
    4. Call CodeValidator to statically analyze code
    5. Call SandboxRunner to test-execute the agent
    6. Register the agent type via register_fn callback
    7. Create a pool for the new agent type
    8. Set probationary trust for all agents in the new pool
    9. Track with BehavioralMonitor
    """

    def __init__(
        self,
        designer: AgentDesigner,
        validator: CodeValidator,
        sandbox: SandboxRunner,
        monitor: BehavioralMonitor,
        config: SelfModConfig,
        register_fn: Callable,  # runtime.register_agent_type
        create_pool_fn: Callable,  # runtime creates a pool for the new type
        set_trust_fn: Callable,  # trust_network.create_with_prior
        user_approval_fn: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self._designer = designer
        self._validator = validator
        self._sandbox = sandbox
        self._monitor = monitor
        self._config = config
        self._register_fn = register_fn
        self._create_pool_fn = create_pool_fn
        self._set_trust_fn = set_trust_fn
        self._user_approval_fn = user_approval_fn
        self._records: list[DesignedAgentRecord] = []

    async def handle_unhandled_intent(
        self,
        intent_name: str,
        intent_description: str,
        parameters: dict[str, str],
        requires_consensus: bool = False,
    ) -> DesignedAgentRecord | None:
        """Full pipeline: design -> validate -> sandbox -> register -> track.

        Returns DesignedAgentRecord if successful, None if any step fails.
        """
        # Check max limit
        active_count = sum(1 for r in self._records if r.status == "active")
        if active_count >= self._config.max_designed_agents:
            logger.warning(
                "Max designed agents (%d) reached, skipping design for %s",
                self._config.max_designed_agents, intent_name,
            )
            return None

        # User approval gate
        if self._config.require_user_approval and self._user_approval_fn:
            description = (
                f"Intent: {intent_name}\n"
                f"Description: {intent_description}\n"
                f"Parameters: {parameters}"
            )
            try:
                approved = await self._user_approval_fn(description)
            except Exception:
                approved = False
            if not approved:
                record = DesignedAgentRecord(
                    intent_name=intent_name,
                    agent_type=intent_name,
                    class_name="",
                    source_code="",
                    created_at=time.monotonic(),
                    status="rejected_by_user",
                )
                self._records.append(record)
                return None

        # 1. Design agent
        try:
            source_code = await self._designer.design_agent(
                intent_name=intent_name,
                intent_description=intent_description,
                parameters=parameters,
                requires_consensus=requires_consensus,
            )
        except Exception as e:
            logger.warning("Agent design failed for %s: %s", intent_name, e)
            return None

        class_name = self._designer._build_class_name(intent_name)
        agent_type = self._designer._build_agent_type(intent_name)

        # 2. Validate
        errors = self._validator.validate(source_code)
        if errors:
            logger.warning("Validation failed for %s: %s", intent_name, errors)
            record = DesignedAgentRecord(
                intent_name=intent_name,
                agent_type=agent_type,
                class_name=class_name,
                source_code=source_code,
                created_at=time.monotonic(),
                status="failed_validation",
            )
            self._records.append(record)
            return None

        # 3. Sandbox test
        sandbox_result = await self._sandbox.test_agent(
            source_code, intent_name, test_params=parameters or {},
        )
        if not sandbox_result.success:
            logger.warning("Sandbox failed for %s: %s", intent_name, sandbox_result.error)
            record = DesignedAgentRecord(
                intent_name=intent_name,
                agent_type=agent_type,
                class_name=class_name,
                source_code=source_code,
                created_at=time.monotonic(),
                sandbox_time_ms=sandbox_result.execution_time_ms,
                status="failed_sandbox",
            )
            self._records.append(record)
            return None

        # 4. Register agent type
        agent_class = sandbox_result.agent_class
        try:
            await self._register_fn(agent_class)
        except Exception as e:
            logger.warning("Registration failed for %s: %s", intent_name, e)
            return None

        # 5. Create pool
        pool_name = f"designed_{agent_type}"
        try:
            await self._create_pool_fn(agent_type, pool_name, 2)
        except Exception as e:
            logger.warning("Pool creation failed for %s: %s", intent_name, e)
            return None

        # 6. Set probationary trust on newly spawned agents
        try:
            await self._set_trust_fn(pool_name)
        except Exception:
            pass

        # 7. Track with behavioral monitor
        self._monitor.track_agent_type(agent_type)

        record = DesignedAgentRecord(
            intent_name=intent_name,
            agent_type=agent_type,
            class_name=class_name,
            source_code=source_code,
            created_at=time.monotonic(),
            sandbox_time_ms=sandbox_result.execution_time_ms,
            pool_name=pool_name,
            status="active",
        )
        self._records.append(record)
        logger.info("Self-designed agent registered: %s (%s)", class_name, agent_type)
        return record

    def designed_agents(self) -> list[DesignedAgentRecord]:
        """Return all designed agent records (active and removed)."""
        return list(self._records)

    def designed_agent_status(self) -> dict:
        """Return status summary for shell/panels."""
        agents = []
        for r in self._records:
            agents.append({
                "intent_name": r.intent_name,
                "agent_type": r.agent_type,
                "class_name": r.class_name,
                "status": r.status,
                "created_at": r.created_at,
                "sandbox_time_ms": r.sandbox_time_ms,
                "pool_name": r.pool_name,
            })
        return {
            "designed_agents": agents,
            "active_count": sum(1 for r in self._records if r.status == "active"),
            "max_designed_agents": self._config.max_designed_agents,
        }
