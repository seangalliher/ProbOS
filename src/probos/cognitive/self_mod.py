"""SelfModificationPipeline — orchestrates agent design, validation, and registration."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.cognitive.agent_designer import AgentDesigner
    from probos.cognitive.behavioral_monitor import BehavioralMonitor
    from probos.cognitive.code_validator import CodeValidator
    from probos.cognitive.dependency_resolver import DependencyResolver
    from probos.cognitive.sandbox import SandboxRunner
    from probos.cognitive.skill_designer import SkillDesigner
    from probos.cognitive.skill_validator import SkillValidator
    from probos.config import SelfModConfig
    from probos.substrate.event_log import EventLog

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
    strategy: str = "new_agent"  # "new_agent" or "skill"
    error: str = ""  # human-readable failure detail (empty on success)


class SelfModificationPipeline:
    """Orchestrates the full self-modification flow.

    Flow:
    1. Check config: is self_mod enabled? Under max_designed_agents?
    2. Ask user for approval to design an agent (if require_user_approval)
    3. Call AgentDesigner to generate code
    4. Call CodeValidator to statically analyze code
    5. DependencyResolver — detect missing packages, prompt user, install
    6. Call SandboxRunner to test-execute the agent
    7. Register the agent type via register_fn callback
    8. Create a pool for the new agent type
    9. Set probationary trust for all agents in the new pool
    10. Track with BehavioralMonitor
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
        unregister_fn: Callable | None = None,  # runtime.unregister_agent_type (AD-368)
        user_approval_fn: Callable[[str], Awaitable[bool]] | None = None,
        skill_designer: SkillDesigner | None = None,
        skill_validator: SkillValidator | None = None,
        add_skill_fn: Callable | None = None,
        research: Any = None,
        dependency_resolver: DependencyResolver | None = None,
        event_log: EventLog | None = None,
    ) -> None:
        self._designer = designer
        self._validator = validator
        self._sandbox = sandbox
        self._monitor = monitor
        self._config = config
        self._register_fn = register_fn
        self._unregister_fn = unregister_fn
        self._create_pool_fn = create_pool_fn
        self._set_trust_fn = set_trust_fn
        self._user_approval_fn = user_approval_fn
        self._skill_designer = skill_designer
        self._skill_validator = skill_validator
        self._add_skill_fn = add_skill_fn
        self._research = research
        self._dependency_resolver = dependency_resolver
        self._event_log = event_log
        self._import_approval_fn: Callable[[list[str]], Awaitable[bool]] | None = None
        self._records: list[DesignedAgentRecord] = []

    async def handle_unhandled_intent(
        self,
        intent_name: str,
        intent_description: str,
        parameters: dict[str, str],
        requires_consensus: bool = False,
        execution_context: str = "",
        on_progress: Callable[[str, int, int], Awaitable[None]] | None = None,
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
            record = DesignedAgentRecord(
                intent_name=intent_name,
                agent_type=intent_name,
                class_name="",
                source_code="",
                created_at=time.monotonic(),
                status="max_limit",
                error=f"Max designed agents ({self._config.max_designed_agents}) reached",
            )
            self._records.append(record)
            return record

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
                    error="User declined self-modification",
                )
                self._records.append(record)
                return record

        # Research phase (optional)
        research_context = "No research available."
        if self._config.research_enabled and self._research:
            try:
                research_context = await self._research.research(
                    intent_name, intent_description, parameters,
                )
            except Exception as e:
                logger.warning("Research failed for %s: %s", intent_name, e)

        # 1. Design agent
        if on_progress:
            try:
                await on_progress("designing", 1, 5)
            except Exception:
                pass
        try:
            source_code = await self._designer.design_agent(
                intent_name=intent_name,
                intent_description=intent_description,
                parameters=parameters,
                requires_consensus=requires_consensus,
                research_context=research_context,
                execution_context=execution_context,
            )
        except Exception as e:
            logger.warning("Agent design failed for %s: %s", intent_name, e)
            record = DesignedAgentRecord(
                intent_name=intent_name,
                agent_type=intent_name,
                class_name="",
                source_code="",
                created_at=time.monotonic(),
                status="failed_design",
                error=f"LLM design failed: {e}",
            )
            self._records.append(record)
            return record

        class_name = self._designer._build_class_name(intent_name)
        agent_type = self._designer._build_agent_type(intent_name)

        # 2. Validate
        if on_progress:
            try:
                await on_progress("validating", 2, 5)
            except Exception:
                pass
        errors = self._validator.validate(source_code)
        if errors:
            # Check if failures are ONLY about forbidden imports
            forbidden = [e for e in errors if e.startswith("Forbidden import:")]
            other = [e for e in errors if not e.startswith("Forbidden import:")]

            if forbidden and not other and self._import_approval_fn:
                import_names = [e.split(":", 1)[1].strip() for e in forbidden]
                try:
                    approved = await self._import_approval_fn(import_names)
                except Exception:
                    approved = False
                if approved:
                    for name in import_names:
                        if name not in self._config.allowed_imports:
                            self._config.allowed_imports.append(name)
                        self._validator._allowed_imports.add(name)
                    # Re-validate with expanded whitelist
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
                    error="Validation: " + "; ".join(errors),
                )
                self._records.append(record)
                return record

        # 2b. Dependency resolution (AD-213)
        if self._dependency_resolver:
            missing = self._dependency_resolver.detect_missing(source_code)
            # AD-215: dependency_check event
            if self._event_log:
                await self._event_log.log(
                    category="self_mod", event="dependency_check",
                    detail=json.dumps({"source": "agent", "missing_count": len(missing), "missing": missing}),
                )
            dep_result = await self._dependency_resolver.resolve(source_code)
            if (dep_result.installed or dep_result.failed) and self._event_log:
                all_packages = dep_result.installed + dep_result.failed
                await self._event_log.log(
                    category="self_mod", event="dependency_install_approved",
                    detail=json.dumps({"packages": all_packages}),
                )
            if dep_result.installed and self._event_log:
                for pkg in dep_result.installed:
                    await self._event_log.log(
                        category="self_mod", event="dependency_install_success",
                        detail=json.dumps({"package": pkg, "import_name": pkg}),
                    )
            if dep_result.declined and self._event_log:
                await self._event_log.log(
                    category="self_mod", event="dependency_install_declined",
                    detail=json.dumps({"packages": dep_result.declined}),
                )
            if dep_result.failed and self._event_log:
                for pkg in dep_result.failed:
                    await self._event_log.log(
                        category="self_mod", event="dependency_install_failed",
                        detail=json.dumps({"package": pkg, "error": dep_result.error or "unknown"}),
                    )
            if not dep_result.success:
                reason = "dependencies_declined" if dep_result.declined else "dependencies_failed"
                logger.warning(
                    "Dependency resolution failed for %s: %s",
                    intent_name, dep_result.error or reason,
                )
                record = DesignedAgentRecord(
                    intent_name=intent_name,
                    agent_type=agent_type,
                    class_name=class_name,
                    source_code=source_code,
                    created_at=time.monotonic(),
                    status=reason,
                    error=f"Dependencies: {dep_result.error or reason}",
                )
                self._records.append(record)
                return record

        # 3. Sandbox test
        if on_progress:
            try:
                await on_progress("testing", 3, 5)
            except Exception:
                pass
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
                error=f"Sandbox: {sandbox_result.error}",
            )
            self._records.append(record)
            return record

        # 4. Register agent type
        if on_progress:
            try:
                await on_progress("deploying", 4, 5)
            except Exception:
                pass
        agent_class = sandbox_result.agent_class
        try:
            await self._register_fn(agent_class)
        except Exception as e:
            logger.warning("Registration failed for %s: %s", intent_name, e)
            record = DesignedAgentRecord(
                intent_name=intent_name,
                agent_type=agent_type,
                class_name=class_name,
                source_code=source_code,
                created_at=time.monotonic(),
                sandbox_time_ms=sandbox_result.execution_time_ms,
                status="failed_registration",
                error=f"Registration: {e}",
            )
            self._records.append(record)
            return record

        # 5. Create pool
        pool_name = f"designed_{agent_type}"
        try:
            await self._create_pool_fn(agent_type, pool_name, 1)
        except Exception as e:
            logger.warning("Pool creation failed for %s: %s", intent_name, e)
            # Rollback registration to avoid phantom agent type (AD-368)
            if self._unregister_fn:
                try:
                    await self._unregister_fn(agent_type)
                except Exception as rollback_err:
                    logger.warning("Registration rollback failed for %s: %s",
                                   agent_type, rollback_err)
            record = DesignedAgentRecord(
                intent_name=intent_name,
                agent_type=agent_type,
                class_name=class_name,
                source_code=source_code,
                created_at=time.monotonic(),
                sandbox_time_ms=sandbox_result.execution_time_ms,
                status="failed_pool",
                error=f"Pool creation: {e}",
            )
            self._records.append(record)
            return record

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

    async def handle_add_skill(
        self,
        intent_name: str,
        intent_description: str,
        parameters: dict[str, str],
        target_agent_type: str,
        research_context: str = "No research available.",
    ) -> DesignedAgentRecord | None:
        """Design and attach a skill instead of creating a new agent.

        Flow:
        1. Call SkillDesigner.design_skill() -> source code
        2. Call SkillValidator.validate() -> static analysis
        3. Compile the handler function (importlib)
        4. Create Skill object with handler
        5. Call add_skill_fn callback to attach to skill agents
        6. Record as DesignedAgentRecord with strategy="skill"
        """
        if not self._skill_designer or not self._skill_validator or not self._add_skill_fn:
            logger.warning("Skill pipeline not configured, falling back to new agent")
            return None

        # Check max limit
        active_count = sum(1 for r in self._records if r.status == "active")
        if active_count >= self._config.max_designed_agents:
            logger.warning(
                "Max designed agents (%d) reached, skipping skill for %s",
                self._config.max_designed_agents, intent_name,
            )
            return None

        # 1. Design skill
        try:
            source_code = await self._skill_designer.design_skill(
                intent_name=intent_name,
                intent_description=intent_description,
                parameters=parameters,
                target_agent_type=target_agent_type,
                research_context=research_context,
            )
        except Exception as e:
            logger.warning("Skill design failed for %s: %s", intent_name, e)
            return None

        # 2. Validate
        errors = self._skill_validator.validate(source_code, intent_name)
        if errors:
            logger.warning("Skill validation failed for %s: %s", intent_name, errors)
            record = DesignedAgentRecord(
                intent_name=intent_name,
                agent_type=target_agent_type,
                class_name=self._skill_designer._build_function_name(intent_name),
                source_code=source_code,
                created_at=time.monotonic(),
                status="failed_validation",
                strategy="skill",
            )
            self._records.append(record)
            return None

        # 2b. Dependency resolution for skills (AD-213)
        if self._dependency_resolver:
            missing = self._dependency_resolver.detect_missing(source_code)
            # AD-215: dependency_check event
            if self._event_log:
                await self._event_log.log(
                    category="self_mod", event="dependency_check",
                    detail=json.dumps({"source": "skill", "missing_count": len(missing), "missing": missing}),
                )
            dep_result = await self._dependency_resolver.resolve(source_code)
            if (dep_result.installed or dep_result.failed) and self._event_log:
                all_packages = dep_result.installed + dep_result.failed
                await self._event_log.log(
                    category="self_mod", event="dependency_install_approved",
                    detail=json.dumps({"packages": all_packages}),
                )
            if dep_result.installed and self._event_log:
                for pkg in dep_result.installed:
                    await self._event_log.log(
                        category="self_mod", event="dependency_install_success",
                        detail=json.dumps({"package": pkg, "import_name": pkg}),
                    )
            if dep_result.declined and self._event_log:
                await self._event_log.log(
                    category="self_mod", event="dependency_install_declined",
                    detail=json.dumps({"packages": dep_result.declined}),
                )
            if dep_result.failed and self._event_log:
                for pkg in dep_result.failed:
                    await self._event_log.log(
                        category="self_mod", event="dependency_install_failed",
                        detail=json.dumps({"package": pkg, "error": dep_result.error or "unknown"}),
                    )
            if not dep_result.success:
                reason = "dependencies_declined" if dep_result.declined else "dependencies_failed"
                logger.warning(
                    "Skill dependency resolution failed for %s: %s",
                    intent_name, dep_result.error or reason,
                )
                record = DesignedAgentRecord(
                    intent_name=intent_name,
                    agent_type=target_agent_type,
                    class_name=self._skill_designer._build_function_name(intent_name),
                    source_code=source_code,
                    created_at=time.monotonic(),
                    status=reason,
                    strategy="skill",
                )
                self._records.append(record)
                return None

        # 3. Compile the handler function
        handler = None
        try:
            import importlib.util
            import sys
            import tempfile
            from pathlib import Path

            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8",
            )
            tmp.write(source_code)
            tmp.flush()
            tmp.close()
            tmp_path = tmp.name
            module_name = f"_probos_skill_{id(source_code)}"

            try:
                spec = importlib.util.spec_from_file_location(module_name, tmp_path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)

                    func_name = self._skill_designer._build_function_name(intent_name)
                    handler = getattr(module, func_name, None)
            finally:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except OSError:
                    pass
                sys.modules.pop(module_name, None)
        except Exception as e:
            logger.warning("Skill compilation failed for %s: %s", intent_name, e)
            return None

        if handler is None:
            logger.warning("Could not find handler function for %s", intent_name)
            return None

        # 4. Create Skill object
        from probos.types import IntentDescriptor, Skill
        skill = Skill(
            name=intent_name,
            descriptor=IntentDescriptor(
                name=intent_name,
                params=parameters,
                description=intent_description,
                requires_reflect=True,
            ),
            source_code=source_code,
            handler=handler,
            created_at=time.monotonic(),
            origin="designed",
        )

        # 5. Attach to skill agents via callback
        try:
            await self._add_skill_fn(skill, target_agent_type=target_agent_type)
        except Exception as e:
            logger.warning("Skill attachment failed for %s: %s", intent_name, e)
            return None

        # 6. Record
        record = DesignedAgentRecord(
            intent_name=intent_name,
            agent_type=target_agent_type,
            class_name=self._skill_designer._build_function_name(intent_name),
            source_code=source_code,
            created_at=time.monotonic(),
            pool_name="skills",
            status="active",
            strategy="skill",
        )
        self._records.append(record)
        self._monitor.track_agent_type(f"skill:{intent_name}")
        logger.info("Skill designed and attached: %s -> %s", intent_name, target_agent_type)
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
