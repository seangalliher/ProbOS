"""AD-515: Warm boot / knowledge restore extracted from ProbOSRuntime.

Restores trust, routing, agents, skills, episodes, workflows, and QA reports
from the knowledge store on boot.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class WarmBootService:
    """Restores runtime state from knowledge store on warm boot."""

    def __init__(
        self,
        *,
        knowledge_store: Any,
        trust_network: Any,
        hebbian_router: Any,
        episodic_memory: Any | None,
        workflow_cache: Any | None,
        config: Any,
        register_designed_agent_fn: Any,
        create_designed_pool_fn: Any,
        add_skill_to_agents_fn: Any,
        qa_reports: dict[str, Any],
        pools: dict[str, Any],
        semantic_layer: Any | None = None,
    ) -> None:
        self._knowledge_store = knowledge_store
        self._trust_network = trust_network
        self._hebbian_router = hebbian_router
        self._episodic_memory = episodic_memory
        self._workflow_cache = workflow_cache
        self._config = config
        self._register_designed_agent_fn = register_designed_agent_fn
        self._create_designed_pool_fn = create_designed_pool_fn
        self._add_skill_to_agents_fn = add_skill_to_agents_fn
        self._qa_reports = qa_reports
        self._pools = pools
        self._semantic_layer = semantic_layer

    async def restore(self) -> None:
        """Warm boot: restore state from the knowledge store (AD-162).

        Load order: trust -> routing -> agents -> skills -> episodes -> workflows -> QA.
        Each step is independent and wrapped in try/except so that partial
        failures don't block other restorations.
        """
        ks = self._knowledge_store
        if ks is None:
            return

        restored: list[str] = []
        _trust_snapshot: dict[str, dict[str, Any]] = {}

        # 1. Trust snapshot -> restore raw Beta parameters (AD-168)
        try:
            snapshot = await ks.load_trust_snapshot()
            if snapshot:
                _trust_snapshot = snapshot
                for agent_id, params in snapshot.items():
                    alpha = params.get("alpha", 2.0)
                    beta = params.get("beta", 2.0)
                    # Force-set even if record already exists from pool creation
                    record = self._trust_network.get_or_create(agent_id)
                    record.alpha = alpha
                    record.beta = beta
                restored.append(f"trust({len(snapshot)} agents)")
        except Exception as e:
            logger.warning("Warm boot: trust restore failed: %s", e)

        # 2. Routing weights -> restore Hebbian weights
        try:
            weights = await ks.load_routing_weights()
            if weights:
                for w in weights:
                    key = (w["source"], w["target"], w.get("rel_type", "intent"))
                    self._hebbian_router._weights[key] = w["weight"]
                    # Also update compat view
                    self._hebbian_router._compat_weights[(w["source"], w["target"])] = w["weight"]
                restored.append(f"routing({len(weights)} weights)")
        except Exception as e:
            logger.warning("Warm boot: routing restore failed: %s", e)

        # 3. Designed agents -> validate + register + pool (AD-163)
        try:
            agents = await ks.load_agents()
            if agents and self._config.self_mod.enabled:
                from probos.cognitive.code_validator import CodeValidator
                validator = CodeValidator(self._config.self_mod)

                for metadata, source_code in agents:
                    agent_type = metadata.get("agent_type", "")
                    try:
                        # AD-163: validate before loading
                        errors = validator.validate(source_code)
                        if errors:
                            logger.warning(
                                "Warm boot: skipping agent %s — validation errors: %s",
                                agent_type, errors,
                            )
                            continue

                        # Dynamic load via importlib
                        import importlib.util
                        import sys
                        import tempfile

                        class_name = metadata.get("class_name", "")
                        tmp = tempfile.NamedTemporaryFile(
                            mode="w", suffix=".py", delete=False, encoding="utf-8",
                        )
                        tmp.write(source_code)
                        tmp.flush()
                        tmp.close()
                        tmp_path = tmp.name
                        module_name = f"_probos_restored_{agent_type}"

                        try:
                            spec = importlib.util.spec_from_file_location(module_name, tmp_path)
                            if spec and spec.loader:
                                module = importlib.util.module_from_spec(spec)
                                sys.modules[module_name] = module
                                spec.loader.exec_module(module)
                                agent_class = getattr(module, class_name, None)
                                if agent_class:
                                    await self._register_designed_agent_fn(agent_class)
                                    pool_name = metadata.get("pool_name", f"designed_{agent_type}")
                                    await self._create_designed_pool_fn(agent_type, pool_name)
                                    # Phase 14c: only set probationary trust for
                                    # agents that do NOT have restored trust records.
                                    pool = self._pools.get(pool_name)
                                    if pool:
                                        for aid in pool.healthy_agents:
                                            if aid not in _trust_snapshot:
                                                self._trust_network.create_with_prior(
                                                    aid,
                                                    alpha=self._config.self_mod.probationary_alpha,
                                                    beta=self._config.self_mod.probationary_beta,
                                                )
                                    restored.append(f"agent({agent_type})")
                                else:
                                    logger.warning(
                                        "Warm boot: class %s not found in restored agent %s",
                                        class_name, agent_type,
                                    )
                        finally:
                            try:
                                Path(tmp_path).unlink(missing_ok=True)
                            except OSError:
                                pass
                    except Exception as e:
                        logger.warning("Warm boot: agent %s restore failed: %s", agent_type, e)
        except Exception as e:
            logger.warning("Warm boot: agent restore failed: %s", e)

        # 4. Skills -> compile + attach to SkillBasedAgent
        try:
            skills = await ks.load_skills()
            if skills and self._config.self_mod.enabled:
                import importlib.util
                import sys
                import tempfile

                for intent_name, source_code, descriptor_dict in skills:
                    try:
                        # Compile handler
                        handler = None
                        func_name = f"handle_{intent_name}"
                        tmp = tempfile.NamedTemporaryFile(
                            mode="w", suffix=".py", delete=False, encoding="utf-8",
                        )
                        tmp.write(source_code)
                        tmp.flush()
                        tmp.close()
                        tmp_path = tmp.name
                        module_name = f"_probos_skill_restored_{intent_name}"

                        try:
                            spec = importlib.util.spec_from_file_location(module_name, tmp_path)
                            if spec and spec.loader:
                                module = importlib.util.module_from_spec(spec)
                                sys.modules[module_name] = module
                                spec.loader.exec_module(module)
                                handler = getattr(module, func_name, None)
                        finally:
                            try:
                                Path(tmp_path).unlink(missing_ok=True)
                            except OSError:
                                pass
                            sys.modules.pop(module_name, None)

                        if handler is None:
                            logger.warning("Warm boot: no handler function for skill %s", intent_name)
                            continue

                        from probos.types import IntentDescriptor as _ID, Skill as _Skill
                        skill_desc = _ID(
                            name=descriptor_dict.get("name", intent_name),
                            params=descriptor_dict.get("params", {}),
                            description=descriptor_dict.get("description", ""),
                            requires_reflect=descriptor_dict.get("requires_reflect", True),
                        )
                        skill_obj = _Skill(
                            name=intent_name,
                            descriptor=skill_desc,
                            source_code=source_code,
                            handler=handler,
                            created_at=descriptor_dict.get("created_at", time.monotonic()),
                            origin="designed",
                        )
                        await self._add_skill_to_agents_fn(skill_obj)
                        restored.append(f"skill({intent_name})")
                    except Exception as e:
                        logger.warning("Warm boot: skill %s restore failed: %s", intent_name, e)
        except Exception as e:
            logger.warning("Warm boot: skill restore failed: %s", e)

        # 5. Episodes -> seed into episodic memory
        try:
            if self._episodic_memory:
                episodes = await ks.load_episodes(limit=self._config.knowledge.max_episodes)
                if episodes:
                    seeded = await self._episodic_memory.seed(episodes)
                    restored.append(f"episodes({seeded})")
        except Exception as e:
            logger.warning("Warm boot: episode restore failed: %s", e)

        # 6. Workflows -> populate cache
        try:
            workflows = await ks.load_workflows()
            if workflows and self._workflow_cache:
                from probos.types import WorkflowCacheEntry

                for entry_dict in workflows:
                    key = entry_dict.get("pattern", "")
                    if not key:
                        continue
                    entry = WorkflowCacheEntry(
                        pattern=key,
                        dag_json=entry_dict.get("dag_json", "{}"),
                        hit_count=entry_dict.get("hit_count", 0),
                        last_hit=datetime.fromisoformat(entry_dict["last_hit"]) if "last_hit" in entry_dict else datetime.now(timezone.utc),
                        created_at=datetime.fromisoformat(entry_dict["created_at"]) if "created_at" in entry_dict else datetime.now(timezone.utc),
                    )
                    self._workflow_cache._cache[key] = entry
                restored.append(f"workflows({len(workflows)})")
        except Exception as e:
            logger.warning("Warm boot: workflow restore failed: %s", e)

        # 7. QA reports -> restore _qa_reports dict
        try:
            qa_reports = await ks.load_qa_reports()
            if qa_reports:
                self._qa_reports.update(qa_reports)
                restored.append(f"qa({len(qa_reports)})")
        except Exception as e:
            logger.warning("Warm boot: QA report restore failed: %s", e)

        if restored:
            logger.info("Warm boot restored: %s", ", ".join(restored))
        else:
            logger.info("Warm boot: no artifacts to restore (clean repo)")

        # Semantic knowledge re-indexing from restored artifacts (AD-243)
        if self._semantic_layer and ks:
            try:
                counts = await self._semantic_layer.reindex_from_store(ks)
                logger.info("Semantic knowledge reindexed: %s", counts)
            except Exception as e:
                logger.warning("Semantic knowledge reindex failed: %s", e)
