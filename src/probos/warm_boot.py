"""AD-515: Warm boot / knowledge restore extracted from ProbOSRuntime.

Restores trust, routing, agents, skills, episodes, workflows, and QA reports
from the knowledge store on boot.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _is_inert_skill_stub(source_code: str) -> bool:
    """Return whether source contains only comments, docstrings, or ``pass``."""
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return False

    for index, node in enumerate(tree.body):
        if isinstance(node, ast.Pass):
            continue
        if (
            index == 0
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        return False
    return True


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

        # 4. Skills -> validate + compile + attach to SkillBasedAgent
        try:
            skills = await ks.load_skills()
            if skills and self._config.self_mod.enabled:
                from probos.cognitive.skill_validator import SkillValidator

                validator = SkillValidator(self._config.self_mod)
                for intent_name, source_code, descriptor_dict in skills:
                    try:
                        attached = await self._restore_skill(
                            intent_name,
                            source_code,
                            descriptor_dict,
                            validator,
                        )
                        if attached:
                            restored.append(f"skill({intent_name})")
                    except Exception as e:
                        logger.warning(
                            "Warm boot: skill %s restore failed before attachment; "
                            "source and descriptor remain preserved for retry: %s",
                            intent_name,
                            e,
                        )
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

    async def _restore_skill(
        self,
        intent_name: str,
        initial_source: str,
        descriptor_dict: Any,
        validator: Any,
    ) -> bool:
        """Restore one skill from at most three stable source snapshots."""
        reread_count = 0

        async def _reread_source() -> str | None:
            nonlocal reread_count
            if reread_count >= 2:
                raise RuntimeError("skill source reread budget exhausted")
            reread_count += 1
            return await self._knowledge_store.load_skill_source(intent_name)

        async def _reread_source_and_quarantine(
        ) -> tuple[str | None, dict[str, Any] | None]:
            nonlocal reread_count
            if reread_count >= 2:
                raise RuntimeError("skill source reread budget exhausted")
            reread_count += 1
            return await self._knowledge_store.load_skill_source_and_quarantine(
                intent_name
            )

        def _rereads_remaining() -> int:
            return 2 - reread_count

        source_code: str | None = initial_source
        candidate_from_reread = False
        for _snapshot_number in range(1, 4):
            if source_code is None:
                return False
            observed_hash = self._skill_source_hash(source_code)
            outcome, next_source = await self._restore_skill_snapshot(
                intent_name,
                source_code,
                observed_hash,
                descriptor_dict,
                validator,
                _reread_source,
                _reread_source_and_quarantine,
                _rereads_remaining,
                candidate_from_reread,
            )
            if outcome == "attached":
                return True
            if outcome == "finished":
                return False
            if outcome == "exhausted":
                break
            if _rereads_remaining() == 0:
                break
            if next_source is None:
                next_source = await _reread_source()
            source_code = next_source
            candidate_from_reread = True

        logger.warning(
            "Warm boot: skill %s exhausted its initial candidate plus two public "
            "source rereads; preserving source, descriptor, and marker without "
            "further execution, attachment, or mutation",
            intent_name,
        )
        return False

    async def _restore_skill_snapshot(
        self,
        intent_name: str,
        source_code: str,
        observed_hash: str,
        descriptor_dict: Any,
        validator: Any,
        reread_source: Callable[[], Awaitable[str | None]],
        reread_source_and_quarantine: Callable[
            [], Awaitable[tuple[str | None, dict[str, Any] | None]]
        ],
        rereads_remaining: Callable[[], int],
        candidate_from_reread: bool,
    ) -> tuple[str, str | None]:
        """Process one source candidate within the bounded public-reread budget."""
        ks = self._knowledge_store
        try:
            marker = await ks.load_skill_quarantine(intent_name)
        except Exception as exc:
            logger.warning(
                "Warm boot: failed to inspect quarantine for skill %s: %s; "
                "stable persisted source will be revalidated",
                intent_name,
                exc,
            )
            return "finished", None
        marker_hash = marker.get("source_sha256") if marker is not None else None

        if not candidate_from_reread:
            current_source = await reread_source()
            if current_source is None:
                return "finished", None
            if self._skill_source_hash(current_source) != observed_hash:
                return "retry", current_source

        if marker_hash == observed_hash:
            if candidate_from_reread:
                current_source = await reread_source()
                if current_source is None:
                    return "finished", None
                if self._skill_source_hash(current_source) != observed_hash:
                    return "retry", current_source
            logger.debug(
                "Warm boot: skill %s remains quarantined for the same stable source "
                "hash; skipping validation and execution until source changes",
                intent_name,
            )
            return "finished", None

        errors = validator.validate(source_code, intent_name)
        if errors:
            if _is_inert_skill_stub(source_code):
                if rereads_remaining() > 0:
                    current_source = await reread_source()
                    if current_source is None:
                        return "finished", None
                    if self._skill_source_hash(current_source) != observed_hash:
                        return "retry", current_source
                removed = await ks.remove_skill(
                    intent_name,
                    expected_source_sha256=observed_hash,
                )
                if not removed:
                    return "retry", None
                logger.info(
                    "Warm boot: skill %s was a provably inert stable stub; "
                    "pruned source, descriptor, and matching quarantine marker",
                    intent_name,
                )
                return "finished", None

            if rereads_remaining() > 0:
                current_source = await reread_source()
                if current_source is None:
                    return "finished", None
                if self._skill_source_hash(current_source) != observed_hash:
                    return "retry", current_source
            quarantined = await ks.quarantine_skill(
                intent_name,
                source_code=source_code,
                expected_source_sha256=observed_hash,
                reason="skill_validation_failed",
                errors=errors,
            )
            if not quarantined:
                return "retry", None
            logger.warning(
                "Warm boot: skill %s failed stable pre-execution validation; "
                "source and descriptor remain preserved behind quarantine",
                intent_name,
            )
            return "finished", None

        if rereads_remaining() == 0:
            return "exhausted", None
        try:
            handler = self._load_skill_handler(intent_name, source_code)
        except Exception as exc:
            return await self._quarantine_loaded_skill_failure(
                intent_name,
                source_code,
                observed_hash,
                "skill_source_load_failed",
                [f"{type(exc).__name__}: {exc}"],
                reread_source,
            )

        runtime_errors = self._loaded_handler_errors(handler, intent_name)
        if runtime_errors:
            return await self._quarantine_loaded_skill_failure(
                intent_name,
                source_code,
                observed_hash,
                "skill_handler_runtime_contract_failed",
                runtime_errors,
                reread_source,
            )

        if not isinstance(descriptor_dict, dict):
            logger.warning(
                "Warm boot: skill %s has a non-mapping descriptor; source and "
                "descriptor remain preserved without attachment",
                intent_name,
            )
            return "finished", None

        if marker is not None and marker_hash is not None:
            await ks.clear_skill_quarantine(
                intent_name,
                expected_source_sha256=marker_hash,
            )

        try:
            current_source, current_marker = await reread_source_and_quarantine()
        except Exception as exc:
            logger.warning(
                "Warm boot: final atomic source/quarantine check failed for skill %s: %s; "
                "preserved source will not be attached",
                intent_name,
                exc,
            )
            return "finished", None
        if current_source is None:
            return "finished", None
        if self._skill_source_hash(current_source) != observed_hash:
            return "retry", current_source
        if current_marker is not None:
            return "finished", None

        from probos.types import IntentDescriptor, Skill

        skill_desc = IntentDescriptor(
            name=descriptor_dict.get("name", intent_name),
            params=descriptor_dict.get("params", {}),
            description=descriptor_dict.get("description", ""),
            requires_reflect=descriptor_dict.get("requires_reflect", True),
        )
        skill_obj = Skill(
            name=intent_name,
            descriptor=skill_desc,
            source_code=source_code,
            handler=handler,
            created_at=descriptor_dict.get("created_at", time.monotonic()),
            origin="designed",
        )
        try:
            # The production callback attaches synchronously before its first
            # await (persistence is disabled here). Keep this invocation
            # immediately after the locked final state read: no intervening
            # await may let an in-process marker/source mutation overtake it.
            await self._add_skill_to_agents_fn(skill_obj, persist=False)
        except Exception as exc:
            logger.warning(
                "Warm boot: skill %s passed stable source checks but attachment "
                "failed; it remains unhashed and retryable: %s",
                intent_name,
                exc,
            )
            return "finished", None
        return "attached", None

    async def _quarantine_loaded_skill_failure(
        self,
        intent_name: str,
        source_code: str,
        observed_hash: str,
        reason: str,
        errors: list[str],
        reread_source: Callable[[], Awaitable[str | None]],
    ) -> tuple[str, str | None]:
        """Quarantine a post-validation load/runtime failure if source stayed stable."""
        current_source = await reread_source()
        if current_source is None:
            return "finished", None
        if self._skill_source_hash(current_source) != observed_hash:
            return "retry", current_source
        quarantined = await self._knowledge_store.quarantine_skill(
            intent_name,
            source_code=source_code,
            expected_source_sha256=observed_hash,
            reason=reason,
            errors=errors,
        )
        if not quarantined:
            return "retry", None
        logger.warning(
            "Warm boot: skill %s failed its stable loaded-handler contract; "
            "source and descriptor remain preserved behind quarantine",
            intent_name,
        )
        return "finished", None

    @staticmethod
    def _skill_source_hash(source_code: str) -> str:
        """Return the canonical UTF-8 source digest."""
        return hashlib.sha256(source_code.encode("utf-8")).hexdigest()

    @staticmethod
    def _load_skill_handler(intent_name: str, source_code: str) -> Any:
        """Import validated source and return its exact persisted-name handler."""
        import importlib.util
        import sys
        import tempfile

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8",
        )
        tmp.write(source_code)
        tmp.flush()
        tmp.close()
        tmp_path = tmp.name
        module_name = f"_probos_skill_restored_{intent_name}_{id(source_code)}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, tmp_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"No import loader available for skill {intent_name}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return getattr(module, f"handle_{intent_name}", None)
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
            sys.modules.pop(module_name, None)

    @staticmethod
    def _loaded_handler_errors(handler: Any, intent_name: str) -> list[str]:
        """Prove the loaded object still supports the real dispatch call shape."""
        if not inspect.iscoroutinefunction(handler):
            return [f"Loaded handle_{intent_name} is not an async function"]
        try:
            inspect.signature(handler).bind(object(), llm_client=None)
        except (TypeError, ValueError) as exc:
            return [f"Loaded handle_{intent_name} cannot bind dispatch call: {exc}"]
        return []
