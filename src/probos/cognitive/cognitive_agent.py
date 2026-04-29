"""CognitiveAgent — agent whose decide() step consults an LLM guided by instructions."""

from __future__ import annotations

import hashlib
import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from probos.events import EventType
from probos.cognitive.concurrency_manager import ConcurrencyManager
from probos.cognitive.tiered_knowledge import TieredKnowledgeLoader
from probos.substrate.agent import BaseAgent
from probos.types import AnchorFrame, IntentMessage, IntentResult, LLMRequest, Priority, Skill
from probos.utils import format_duration

if TYPE_CHECKING:
    from probos.cognitive.memory_budget import MemoryBudgetManager
    from probos.cognitive.question_classifier import QuestionClassifier, RetrievalStrategySelector
    from probos.cognitive.spreading_activation import SpreadingActivationEngine
    from probos.cognitive.thought_store import ThoughtStore
    from probos.config import MemoryBudgetConfig

logger = logging.getLogger(__name__)

# Module-level decision cache keyed by agent_type (AD-272)
_DECISION_CACHES: dict[str, dict[str, tuple[dict, float, float]]] = {}
# {agent_type: {hash: (decision_dict, created_at_monotonic, ttl_seconds)}}
_CACHE_HITS: dict[str, int] = {}
_CACHE_MISSES: dict[str, int] = {}

# PROBOS_SKILL_DEBUG=1 — verbose skill loading diagnostics at INFO level.
# Shows why augmentation skills matched/missed, proficiency gate results,
# and catalog state. Toggle on to diagnose skill injection issues.
_SKILL_DEBUG = os.environ.get("PROBOS_SKILL_DEBUG", "").lower() in ("1", "true", "yes")

# AD-632f: Intents eligible for multi-step sub-task chain activation.
_CHAIN_ELIGIBLE_INTENTS: frozenset[str] = frozenset({
    "ward_room_notification",
    "proactive_think",
})


class SensoriumLayer(StrEnum):
    """AD-666: Three-layer classification for agent context injections."""

    PROPRIOCEPTION = "proprioception"
    INTEROCEPTION = "interoception"
    EXTEROCEPTION = "exteroception"


def derive_communication_context(
    channel_name: str,
    is_dm_channel: bool = False,
) -> str:
    """AD-649: Derive communication register context from channel metadata."""
    if is_dm_channel or channel_name.startswith("dm-"):
        return "private_conversation"
    if channel_name == "bridge":
        return "bridge_briefing"
    if channel_name == "recreation":
        return "casual_social"
    if channel_name in ("general", "all-hands"):
        return "ship_wide"
    return "department_discussion"


def _classify_concurrency_priority(intent: IntentMessage) -> int:
    """AD-672: Map intent to concurrency priority on a 0-10 scale."""
    is_captain = intent.params.get("is_captain", False)
    was_mentioned = intent.params.get("was_mentioned", False)
    is_dm = intent.params.get("is_dm_channel", False) or intent.intent == "direct_message"

    if is_captain or was_mentioned:
        return 10
    if is_dm:
        return 8
    if intent.intent == "ward_room_notification":
        return 5
    if intent.intent == "proactive_think":
        return 2
    return 5


class CognitiveAgent(BaseAgent):
    """Agent whose decide() step consults an LLM guided by instructions.

    The perceive/decide/act/report lifecycle is preserved.  ``decide()``
    invokes the LLM with ``instructions`` as the system prompt and the
    current observation (from ``perceive()``) as the user message.
    ``act()`` executes based on the LLM's decision — subclasses override
    it for structured output parsing.
    """

    tier = "domain"  # Cognitive agents are domain-tier by default

    # Default cache TTL — overridden by _get_cache_ttl() based on instructions
    _cache_ttl_seconds: float = 300.0  # 5 minutes

    # Subclasses MUST set these (or pass via __init__)
    instructions: str | None = None
    agent_type: str = "cognitive"
    _task_context: Any = None
    _question_classifier: QuestionClassifier | None = None
    _retrieval_strategy_selector: RetrievalStrategySelector | None = None

    # AD-666: Agent Sensorium Registry — formal inventory of context injections.
    SENSORIUM_REGISTRY: ClassVar[dict[str, tuple[SensoriumLayer, str]]] = {
        "_build_temporal_context": (SensoriumLayer.PROPRIOCEPTION, "Time, age, uptime, crew complement"),
        "_get_comm_proficiency_guidance": (SensoriumLayer.PROPRIOCEPTION, "Communication tier guidance"),
        "_detect_self_in_content": (SensoriumLayer.PROPRIOCEPTION, "Cross-context self-recognition"),
        "_build_dm_self_monitoring": (SensoriumLayer.PROPRIOCEPTION, "DM repetition self-detection"),
        "_confabulation_guard": (SensoriumLayer.PROPRIOCEPTION, "Authority-calibrated confab guard"),
        "_build_crew_complement": (SensoriumLayer.PROPRIOCEPTION, "Anti-confabulation crew roster"),
        "_build_cognitive_baseline": (SensoriumLayer.INTEROCEPTION, "Universal injection: temporal, WM, metrics, ontology"),
        "_build_cognitive_extensions": (SensoriumLayer.INTEROCEPTION, "Proactive-conditional: self-mon, telemetry, overrides"),
        "_build_cognitive_state": (SensoriumLayer.INTEROCEPTION, "Meta-method: merges baseline + extensions"),
        "_format_memory_section": (SensoriumLayer.INTEROCEPTION, "Episodic memories with anchor context"),
        "_build_situation_awareness": (SensoriumLayer.EXTEROCEPTION, "WR activity, alerts, events, infra, subordinates"),
        "_build_active_game_context": (SensoriumLayer.EXTEROCEPTION, "Active game board state"),
        "_build_user_message": (SensoriumLayer.EXTEROCEPTION, "Primary prompt assembly (DM/WR paths)"),
    }

    def __init__(self, **kwargs: Any) -> None:
        # Extract instructions from kwargs if provided (overrides class attr)
        if "instructions" in kwargs:
            self.instructions = kwargs.pop("instructions")

        super().__init__(**kwargs)

        # LLM client from kwargs (same pattern as designed agents)
        self._llm_client = kwargs.get("llm_client")

        # Runtime reference for mesh sub-intent dispatch
        self._runtime = kwargs.get("runtime")

        # Skills dict (AD-199)
        self._skills: dict[str, Skill] = {}

        # Strategy advisor (AD-384) — optional cross-agent knowledge transfer
        self._strategy_advisor = None

        # AD-534b: near-miss/failure context for fallback learning
        self._last_fallback_info: dict[str, Any] | None = None

        # AD-423c: ToolContext, set during onboarding
        self.tool_context: Any = None

        # AD-573: Unified working memory — cognitive continuity across pathways
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        self._working_memory = AgentWorkingMemory()

        # AD-585: Tiered knowledge loader, set via set_knowledge_loader().
        self._knowledge_loader: TieredKnowledgeLoader | None = None

        # AD-632a: Sub-task protocol executor and pending chain
        self._sub_task_executor = None
        self._pending_sub_task_chain = None

        # AD-595e: Cached qualification standing (TTL-refreshed)
        self._qualification_standing: dict | None = None
        self._qualification_standing_ts: float = 0.0
        self._qualification_standing_ttl: float = 300.0  # 5 min

        # AD-672: Per-agent concurrency management
        self._concurrency_manager: ConcurrencyManager | None = None

        # AD-594: Crew Consultation Protocol
        self._consultation_protocol: Any = None

        # AD-602: Question-adaptive retrieval
        self._question_classifier: QuestionClassifier | None = None
        self._retrieval_strategy_selector: RetrievalStrategySelector | None = None
        self._spreading_activation: SpreadingActivationEngine | None = None  # AD-604
        self._thought_store: ThoughtStore | None = None  # AD-606
        self._current_correlation_id: str = ""

        # AD-573: Per-cycle memory budget configuration
        self._memory_budget_config: MemoryBudgetConfig | None = kwargs.get("memory_budget_config")

        # AD-586: Task-contextual standing orders
        self._task_context: Any = None

        # Validate instructions exist
        if not self.instructions:
            raise ValueError(
                f"{self.__class__.__name__} requires non-empty instructions"
            )

    def set_strategy_advisor(self, advisor) -> None:
        """Attach a StrategyAdvisor for cross-agent knowledge transfer (AD-384)."""
        self._strategy_advisor = advisor

    def set_knowledge_loader(self, loader: TieredKnowledgeLoader) -> None:
        """Attach a TieredKnowledgeLoader for tiered knowledge injection (AD-585)."""
        self._knowledge_loader = loader

    def set_task_context(self, ctx: Any) -> None:
        """AD-586: Wire task context for contextual standing orders."""
        self._task_context = ctx

    def set_orientation(self, rendered: str, context: Any = None) -> None:
        """AD-567g / BF-113: Set orientation text and context (public setter for LoD)."""
        self._orientation_rendered = rendered
        self._orientation_context = context

    def set_sub_task_executor(self, executor) -> None:
        """AD-632a: Wire sub-task executor for Level 3 reasoning."""
        self._sub_task_executor = executor

    def set_consultation_protocol(self, protocol: Any) -> None:
        """AD-594: Wire consultation protocol and register as handler."""
        self._consultation_protocol = protocol
        if protocol is not None:
            protocol.register_handler(self.id, self.handle_consultation_request)

    def set_concurrency_manager(self, manager: ConcurrencyManager) -> None:
        """AD-672: Wire per-agent concurrency manager."""
        self._concurrency_manager = manager

    async def _refresh_qualification_standing(self) -> None:
        """AD-595e: Refresh cached qualification standing (TTL-based).

        Looks up standing via runtime.ontology.billet_registry. Degrades
        gracefully — sets None if unavailable.
        """
        now = time.monotonic()
        if (
            getattr(self, '_qualification_standing', None) is not None
            and now - getattr(self, '_qualification_standing_ts', 0) < getattr(self, '_qualification_standing_ttl', 300)
        ):
            return  # Cache still fresh

        try:
            rt = getattr(self, 'runtime', None)
            if not rt:
                return
            ontology = getattr(rt, 'ontology', None)
            if not ontology:
                return
            billet_reg = getattr(ontology, 'billet_registry', None)
            if not billet_reg:
                return

            self._qualification_standing = await billet_reg.get_qualification_standing(
                self.agent_type, agent_id=self.id,
            )
            self._qualification_standing_ts = now
        except Exception:
            logger.debug("AD-595e: Qualification standing refresh failed", exc_info=True)

    @property
    def working_memory(self):
        """AD-573: Agent's unified working memory — active situation model."""
        return self._working_memory

    @property
    def _cognitive_journal(self):
        """AD-431: Access journal via runtime (Ship's Computer service)."""
        if self._runtime and hasattr(self._runtime, 'cognitive_journal'):
            return self._runtime.cognitive_journal
        return None

    @property
    def _procedure_store(self):
        """AD-534: Access procedure store via runtime (Ship's Computer service)."""
        if self._runtime and hasattr(self._runtime, 'procedure_store'):
            return self._runtime.procedure_store
        return None

    async def _check_procedural_memory(self, observation: dict) -> dict | None:
        """AD-534: Check for a matching procedure before calling the LLM.

        Returns a decision dict if a procedure was replayed successfully,
        or None to fall through to the LLM path.
        """
        self._last_fallback_info = None  # AD-534b: reset for this cycle

        store = self._procedure_store
        if not store:
            return None

        # Extract query text from observation
        params = observation.get("params", {})
        query = ""
        if isinstance(params, dict):
            query = params.get("message", "") or params.get("query", "")
        if not query:
            query = observation.get("intent", "")
        if not query:
            return None

        from probos.config import (
            PROCEDURE_MATCH_THRESHOLD,
            PROCEDURE_MIN_COMPILATION_LEVEL,
        )

        # 1. Negative procedure check — warn even before positive match
        try:
            neg_matches = await store.find_matching(
                query, n_results=3, exclude_negative=False,
            )
            for nm in neg_matches:
                if nm.get("is_negative") and nm.get("score", 0) >= PROCEDURE_MATCH_THRESHOLD:
                    logger.warning(
                        "AD-534: Negative procedure match for '%s': %s (score=%.3f). "
                        "Avoiding known anti-pattern.",
                        query[:50], nm.get("name"), nm.get("score"),
                    )
                    # AD-534b: Near-miss tracking — negative veto
                    self._last_fallback_info = {
                        "type": "negative_veto",
                        "procedure_id": nm["id"],
                        "procedure_name": nm.get("name", ""),
                        "score": nm["score"],
                        "reason": "Blocked by negative procedure (anti-pattern match)",
                    }
                    # Don't return — fall through to LLM with warning logged.
                    # The LLM path will handle the task correctly.
                    return None
        except Exception:
            logger.debug("Negative procedure check failed (non-critical)", exc_info=True)

        # 2. Find matching positive procedures
        try:
            matches = await store.find_matching(
                query,
                n_results=3,
                min_compilation_level=PROCEDURE_MIN_COMPILATION_LEVEL,
                exclude_negative=True,
            )
        except Exception:
            logger.debug("Procedure store query failed (non-critical)", exc_info=True)
            return None

        if not matches:
            return None

        best = matches[0]

        # 3. Score threshold gate
        if best.get("score", 0) < PROCEDURE_MATCH_THRESHOLD:
            # AD-534b: Near-miss tracking — score below threshold
            self._last_fallback_info = {
                "type": "score_threshold",
                "procedure_id": best["id"],
                "procedure_name": best.get("name", ""),
                "score": best.get("score", 0),
                "reason": f"Score {best.get('score', 0):.2f} below threshold {PROCEDURE_MATCH_THRESHOLD}",
            }
            return None

        # 4. Quality metric gate — don't replay procedures with poor track record
        try:
            metrics = await store.get_quality_metrics(best["id"])
        except Exception:
            metrics = {}

        if metrics.get("total_selections", 0) >= 5:
            eff_rate = metrics.get("effective_rate", 1.0)
            if eff_rate < 0.3:
                logger.info(
                    "AD-534: Skipping procedure '%s' — poor effective_rate (%.2f)",
                    best.get("name"), eff_rate,
                )
                self._diagnose_procedure_health(best["id"], best.get("name", ""), metrics)
                # AD-534b: Near-miss tracking — quality gate
                self._last_fallback_info = {
                    "type": "quality_gate",
                    "procedure_id": best["id"],
                    "procedure_name": best.get("name", ""),
                    "score": best.get("score", 0),
                    "metrics": metrics,
                    "reason": f"Effective rate {eff_rate:.2f} below 0.3",
                }
                return None

        # 5. Record selection
        try:
            await store.record_selection(best["id"])
        except Exception:
            logger.debug("record_selection failed", exc_info=True)

        # 6. Load full procedure
        try:
            procedure = await store.get(best["id"])
        except Exception:
            logger.debug("Procedure load failed", exc_info=True)
            return None

        if not procedure:
            return None

        # 7. Record applied (replay attempt begins)
        try:
            await store.record_applied(best["id"])
        except Exception:
            logger.debug("record_applied failed", exc_info=True)

        # AD-535: Trust-tier clamping
        trust_score = getattr(self, "_trust_score", 0.5)
        max_level = self._max_compilation_level_for_trust(trust_score)
        # AD-537: Promoted procedures can reach Level 5 (Expert)
        if procedure.compilation_level >= 5 and self._procedure_store:
            try:
                promo_status = await self._procedure_store.get_promotion_status(procedure.id)
                max_level = self._max_compilation_level_for_promoted(trust_score, promo_status)
            except Exception:
                pass
        effective_level = min(procedure.compilation_level, max_level)

        # AD-535: Level-based dispatch
        if effective_level <= 1:
            # Level 1 (Novice): Should not reach here — find_matching() filters by
            # min_compilation_level. If it does, fall through to LLM.
            return None

        elif effective_level == 2:
            # Level 2 (Guided): LLM + procedure hints
            return await self._build_guided_decision(procedure, observation, best.get("score", 0))

        elif effective_level == 3:
            # Level 3 (Validated): Deterministic replay + LLM validation
            return await self._build_validated_decision(procedure, observation, best.get("score", 0))

        # Level 4+ (Autonomous/Expert): Zero-token replay
        # 8. Execute replay
        try:
            replay_output = self._format_procedure_replay(procedure, best.get("score", 0))

            # AD-534b: record_completion moved to handle_intent() post-execution

            # Health diagnosis (log-only, feeds future AD-532b)
            try:
                updated_metrics = await store.get_quality_metrics(best["id"])
                self._diagnose_procedure_health(best["id"], procedure.name, updated_metrics)
            except Exception:
                logger.debug("Health diagnosis failed (non-critical)", exc_info=True)

            logger.info(
                "AD-534: Procedure replay for '%s' — '%s' (score=%.3f, 0 tokens)",
                observation.get("intent", ""), procedure.name, best.get("score", 0),
            )

            # AD-534c: detect compound procedure (any step has agent_role set)
            is_compound = any(
                getattr(step, "agent_role", "") for step in procedure.steps
            )

            result_dict = {
                "action": "execute",
                "llm_output": replay_output,
                "cached": True,
                "procedure_id": procedure.id,
                "procedure_name": procedure.name,
            }
            if is_compound:
                result_dict["compound"] = True
                result_dict["procedure"] = procedure

            return result_dict

        except Exception as exc:
            # Replay failed — record near-miss info, fall through to LLM
            logger.info(
                "AD-534: Procedure replay failed for '%s' — falling back to LLM",
                procedure.name,
            )
            # AD-534b: record_fallback moved to handle_intent() post-execution
            self._last_fallback_info = {
                "type": "format_exception",
                "procedure_id": procedure.id,
                "procedure_name": procedure.name,
                "score": best.get("score", 0),
                "reason": f"Replay formatting failed: {exc}",
            }
            return None

    def _format_single_step(self, step: Any) -> str:
        """AD-534c: Format a single ProcedureStep for dispatch or local replay."""
        role = getattr(step, "agent_role", "")
        if role:
            line = f"**Step {step.step_number} [{role}]:** {step.action}"
        else:
            line = f"**Step {step.step_number}:** {step.action}"

        if getattr(step, "expected_output", ""):
            line += f"\n  \u2192 Expected: {step.expected_output}"

        return line

    def _format_procedure_replay(self, procedure: Any, match_score: float = 0.0) -> str:
        """AD-534: Format a procedure for deterministic replay output.

        The procedure's steps become the structured response,
        replacing the LLM call entirely.
        """
        lines = [
            f"[Procedure Replay: {procedure.name}]",
            f"Match score: {match_score:.3f} | Steps: {len(procedure.steps)}",
            "",
        ]
        if procedure.description:
            lines.append(procedure.description)
            lines.append("")

        for step in procedure.steps:
            lines.append(self._format_single_step(step))
            if getattr(step, "fallback_action", ""):
                lines.append(f"  \u26a0 Fallback: {step.fallback_action}")

        if procedure.postconditions:
            lines.append("")
            lines.append("**Postconditions:**")
            for pc in procedure.postconditions:
                lines.append(f"  - {pc}")

        return "\n".join(lines)

    def _resolve_step_agent(self, step: Any) -> str | None:
        """AD-534c: Resolve a ProcedureStep to a live agent ID.

        Three-stage resolution:
          1. resolved_agent_type → registry.get_by_pool() → first live agent
          2. agent_role → registry.get_by_capability() → first live agent
          3. Return None if both fail

        Skips self (orchestrating agent). Returns the agent_id or None.
        """
        _rt = getattr(self, '_runtime', None)
        if not _rt or not hasattr(_rt, 'registry'):
            return None

        registry = _rt.registry

        # Stage 1: resolved_agent_type → get_by_pool
        resolved_type = getattr(step, "resolved_agent_type", "")
        if resolved_type:
            try:
                pool_agents = registry.get_by_pool(resolved_type)
                for agent in pool_agents:
                    if agent.id != self.id and getattr(agent, 'is_alive', False):
                        return agent.id
            except Exception:
                logger.debug("AD-534c: get_by_pool('%s') failed", resolved_type, exc_info=True)

        # Stage 2: agent_role → get_by_capability
        role = getattr(step, "agent_role", "")
        if role:
            try:
                cap_agents = registry.get_by_capability(role)
                for agent in cap_agents:
                    if agent.id != self.id and getattr(agent, 'is_alive', False):
                        return agent.id
            except Exception:
                logger.debug("AD-534c: get_by_capability('%s') failed", role, exc_info=True)

        # Stage 3: no match
        return None

    async def _execute_compound_replay(
        self, procedure: Any, text_fallback: str, compilation_level: int = 4
    ) -> dict:
        """AD-534c: Dispatch compound procedure steps to appropriate agents.

        Resolves each step's agent_role to a live agent. Dispatches steps
        sequentially via IntentBus.send() with 'compound_step_replay' intent.
        Target agents receive pre-formatted step text and return it (zero tokens).

        Degrades to single-agent text replay if any required agent is unavailable
        or if IntentBus/registry are not available.
        """
        from probos.config import COMPOUND_STEP_TIMEOUT_SECONDS

        _rt = getattr(self, '_runtime', None)
        if not _rt or not hasattr(_rt, 'intent_bus') or not hasattr(_rt, 'registry'):
            logger.debug("AD-534c: IntentBus or registry unavailable, degrading to text replay")
            return {"success": True, "result": text_fallback, "compound_dispatched": False, "steps_dispatched": 0}

        intent_bus = _rt.intent_bus

        # Build dispatch plan: list of (step, target_agent_id or None)
        dispatch_plan: list[tuple[Any, str | None]] = []
        for step in procedure.steps:
            role = getattr(step, "agent_role", "")
            if not role:
                # No role assigned — local step
                dispatch_plan.append((step, None))
                continue

            agent_id = self._resolve_step_agent(step)
            if agent_id is None:
                # Can't resolve — degrade to single-agent text replay
                logger.warning(
                    "AD-534c: Cannot resolve agent for role '%s' in procedure '%s'. "
                    "Degrading to single-agent replay.",
                    role, procedure.name,
                )
                self._last_fallback_info = {
                    "type": "compound_agent_unavailable",
                    "procedure_id": procedure.id,
                    "procedure_name": procedure.name,
                    "reason": f"No agent available for role '{role}'",
                }
                return {"success": True, "result": text_fallback, "compound_dispatched": False, "steps_dispatched": 0}

            dispatch_plan.append((step, agent_id))

        # Dispatch loop
        results: list[str] = []
        for step, target_agent_id in dispatch_plan:
            step_text = self._format_single_step(step)

            if target_agent_id is None:
                # Local step — no dispatch needed
                results.append(step_text)
                continue

            # Dispatch via IntentBus
            intent = IntentMessage(
                intent="compound_step_replay",
                params={
                    "step_text": step_text,
                    "procedure_id": procedure.id,
                    "step_number": step.step_number,
                },
                target_agent_id=target_agent_id,
                ttl_seconds=COMPOUND_STEP_TIMEOUT_SECONDS,
            )

            try:
                intent_result = await intent_bus.send(intent)
                if intent_result and intent_result.success:
                    step_result_text = intent_result.result or step_text
                    results.append(step_result_text)
                else:
                    logger.warning(
                        "AD-534c: Step %d dispatch to '%s' failed. Using text fallback.",
                        step.step_number, target_agent_id,
                    )
                    step_result_text = step_text
                    results.append(step_text)
            except Exception:
                logger.debug("AD-534c: Step %d dispatch exception", step.step_number, exc_info=True)
                step_result_text = step_text
                results.append(step_text)

            # AD-535: Level 3 per-step postcondition validation
            if compilation_level == 3 and step.expected_output:
                step_valid = await self._validate_step_postcondition(
                    step, step_result_text
                )
                if not step_valid:
                    logger.info(
                        "Compound step %d validation failed — aborting compound replay",
                        step.step_number,
                    )
                    return {"success": True, "result": text_fallback, "compound_dispatched": False, "compound_aborted": True}

        assembled = "\n\n".join(results)
        return {
            "success": True,
            "result": assembled,
            "compound_dispatched": True,
            "steps_dispatched": sum(1 for _, tid in dispatch_plan if tid is not None),
        }

    async def _handle_compound_step_replay(self, intent: IntentMessage) -> IntentResult:
        """AD-534c: Handle a dispatched compound procedure step.

        Zero-token operation — receives pre-formatted step text and returns it.
        No LLM invocation.
        """
        step_text = intent.params.get("step_text", "")
        procedure_id = intent.params.get("procedure_id", "")
        step_number = intent.params.get("step_number", 0)

        logger.debug(
            "AD-534c: Agent %s received compound step %d from procedure %s",
            self.id, step_number, procedure_id,
        )

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=True,
            result=step_text,
            confidence=1.0,
        )

    async def _build_guided_decision(
        self, procedure: Any, observation: dict, match_score: float
    ) -> dict:
        """AD-535 Level 2 (Guided): Call LLM with procedure steps injected as hints.

        The LLM reasons freely but has the learned procedure as scaffolding.
        ~40% token reduction vs full reasoning from scratch.
        """
        hints = self._format_procedure_as_hints(procedure)

        guided_observation = dict(observation)
        guided_observation["procedure_hints"] = hints
        guided_observation["procedure_guidance"] = (
            f"A learned procedure '{procedure.name}' suggests the following approach. "
            f"Use these steps as guidance but apply your own judgment:\n\n{hints}"
        )

        decision = await self._decide_via_llm(guided_observation)

        decision["guided_by_procedure"] = True
        decision["procedure_id"] = procedure.id
        decision["procedure_name"] = procedure.name
        decision["compilation_level"] = 2
        return decision

    def _format_procedure_as_hints(self, procedure: Any) -> str:
        """AD-535: Format procedure steps as guidance hints for Level 2 (Guided) replay.

        Differs from _format_procedure_replay() — framed as suggestions, not directives.
        Includes expected_input/output for each step as orientation.
        """
        lines = [f"Suggested approach based on prior success ('{procedure.name}'):"]
        for step in procedure.steps:
            line = f"  {step.step_number}. {step.action}"
            if step.expected_input:
                line += f"\n     Context: {step.expected_input}"
            if step.expected_output:
                line += f"\n     Expected result: {step.expected_output}"
            role = getattr(step, "agent_role", "")
            if role:
                line += f"\n     (Typically performed by: {role})"
            lines.append(line)
        if procedure.postconditions:
            lines.append(f"\nSuccess criteria: {procedure.postconditions}")
        return "\n".join(lines)

    async def _build_validated_decision(
        self, procedure: Any, observation: dict, match_score: float
    ) -> dict | None:
        """AD-535 Level 3 (Validated): Deterministic replay + LLM postcondition validation.

        Execute procedure deterministically (same as Level 4), then call LLM
        to validate the result against expected outcomes. ~80% token reduction.
        If validation fails, return None to trigger LLM fallback.
        """
        replay_output = self._format_procedure_replay(procedure, match_score)

        validation_passed = await self._validate_replay_postconditions(
            procedure, replay_output, observation
        )

        if not validation_passed:
            self._last_fallback_info = {
                "type": "validation_failure",
                "procedure_id": procedure.id,
                "procedure_name": procedure.name,
                "score": match_score,
                "compilation_level": 3,
            }
            logger.info(
                "Level 3 validation failed for procedure %s — falling back to LLM",
                procedure.name,
            )
            return None

        is_compound = any(
            getattr(step, "resolved_agent_type", "") for step in procedure.steps
        ) and len(procedure.steps) >= 2

        decision = {
            "action": "execute",
            "llm_output": replay_output,
            "cached": True,
            "procedure_id": procedure.id,
            "procedure_name": procedure.name,
            "compilation_level": 3,
            "validated": True,
        }
        if is_compound:
            decision["compound"] = True
            decision["procedure"] = procedure

        return decision

    async def _validate_replay_postconditions(
        self, procedure: Any, replay_output: str, observation: dict
    ) -> bool:
        """AD-535: Validate deterministic replay output against procedure postconditions.

        Uses a small LLM call to check whether the output satisfies expected outcomes.
        Returns True if validation passes, False otherwise.
        """
        import asyncio

        from probos.config import COMPILATION_VALIDATION_TIMEOUT_SECONDS

        validation_context = []

        if procedure.postconditions:
            if isinstance(procedure.postconditions, list):
                for pc in procedure.postconditions:
                    validation_context.append(f"Expected postcondition: {pc}")
            else:
                validation_context.append(f"Expected postconditions: {procedure.postconditions}")

        for step in procedure.steps:
            if step.expected_output:
                validation_context.append(
                    f"Step {step.step_number} expected output: {step.expected_output}"
                )
            if step.invariants:
                for inv in step.invariants:
                    validation_context.append(f"Step {step.step_number} invariant: {inv}")

        if not validation_context:
            return True

        validation_prompt = (
            "You are a postcondition validator. Given the following procedure replay output "
            "and expected outcomes, determine if the output satisfies the expectations.\n\n"
            f"Procedure: {procedure.name}\n"
            f"Replay output:\n{replay_output[:2000]}\n\n"
            f"Expected outcomes:\n" + "\n".join(validation_context) + "\n\n"
            "Does the output satisfy the expected outcomes? "
            "Answer ONLY 'YES' or 'NO' followed by a brief reason."
        )

        try:
            llm_client = getattr(self, "_llm_client", None)
            if not llm_client:
                return True

            response = await asyncio.wait_for(
                llm_client.generate(validation_prompt, max_tokens=100),
                timeout=COMPILATION_VALIDATION_TIMEOUT_SECONDS,
            )

            answer = response.strip().upper()
            return answer.startswith("YES")

        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning(
                "Level 3 validation call failed for procedure %s: %s — passing by default",
                procedure.name, exc,
            )
            return True

    async def _validate_step_postcondition(
        self, step: Any, actual_output: str
    ) -> bool:
        """AD-535: Validate a single step's output against its expected_output.

        Small LLM call. Used at Level 3 during compound replay.
        """
        import asyncio

        from probos.config import COMPILATION_VALIDATION_TIMEOUT_SECONDS

        if not step.expected_output:
            return True

        prompt = (
            f"Step {step.step_number}: {step.action}\n"
            f"Actual output: {actual_output[:1000]}\n"
            f"Expected output: {step.expected_output}\n\n"
            "Does the actual output satisfy the expected output? YES or NO."
        )

        try:
            llm_client = getattr(self, "_llm_client", None)
            if not llm_client:
                return True
            response = await asyncio.wait_for(
                llm_client.generate(prompt, max_tokens=50),
                timeout=COMPILATION_VALIDATION_TIMEOUT_SECONDS,
            )
            return response.strip().upper().startswith("YES")
        except Exception:
            return True  # Fail-open

    def _diagnose_procedure_health(
        self, procedure_id: str, procedure_name: str, metrics: dict
    ) -> None:
        """AD-534: Metric-based health diagnosis (OpenSpace absorbed pattern).

        Uses shared diagnosis function from procedures.py. Logs diagnosis for
        AD-532b FIX/DERIVED evolution. No action taken here.
        """
        from probos.cognitive.procedures import diagnose_procedure_health
        from probos.config import PROCEDURE_MIN_SELECTIONS

        diagnosis = diagnose_procedure_health(metrics, min_selections=PROCEDURE_MIN_SELECTIONS)
        if diagnosis:
            logger.warning(
                "AD-534: Procedure health diagnosis for '%s' (%s): %s "
                "(selections=%d, fallback=%.2f, applied=%.2f, completion=%.2f, effective=%.2f)",
                procedure_name, procedure_id[:8], diagnosis,
                metrics.get("total_selections", 0),
                metrics.get("fallback_rate", 0.0),
                metrics.get("applied_rate", 0.0),
                metrics.get("completion_rate", 0.0),
                metrics.get("effective_rate", 0.0),
            )

    def _max_compilation_level_for_trust(self, trust_score: float) -> int:
        """AD-535: Return the maximum compilation level allowed for the given trust score.

        Ensign (trust < 0.5): Levels 1-2 (Novice, Guided)
        Lieutenant (trust 0.5+): Levels 1-4 (full range)
        AD-536: Promoted procedures can reach Level 5 (Expert) at Commander+ trust.
        """
        from probos.config import (
            COMPILATION_TRUST_LEVEL_3_MIN,
            COMPILATION_MAX_LEVEL,
        )
        if trust_score < COMPILATION_TRUST_LEVEL_3_MIN:
            return 2  # Ensign: max Level 2 (Guided)
        return min(4, COMPILATION_MAX_LEVEL)  # Lieutenant+: max Level 4

    def _max_compilation_level_for_promoted(self, trust_score: float, promotion_status: str) -> int:
        """AD-536: Level 5 unlock for promoted procedures with Commander+ trust."""
        from probos.config import TRUST_COMMANDER
        base = self._max_compilation_level_for_trust(trust_score)
        if promotion_status == "approved" and trust_score >= TRUST_COMMANDER:
            return 5  # Expert level unlocked for promoted procedures
        return base

    # ------------------------------------------------------------------
    # AD-536: Procedure Promotion Helpers
    # ------------------------------------------------------------------

    _DEPARTMENT_CHIEFS: dict[str, str] = {
        "engineering": "laforge",
        "medical": "bones",
        "science": "number_one",  # dual-hatted
        "security": "worf",
        "operations": "obrien",
        "bridge": "captain",  # Bridge procedures always go to Captain
    }

    async def _request_procedure_promotion(self, procedure_id: str) -> dict | None:
        """AD-536: Request institutional promotion for a proven procedure."""
        _store = self._procedure_store
        if not _store:
            return None
        try:
            result = await _store.request_promotion(procedure_id)
            if result.get("eligible"):
                await self._announce_promotion_request(procedure_id, result)
                return result
            else:
                logger.debug(
                    "AD-536: Procedure %s not eligible for promotion: %s",
                    procedure_id, result.get("reason"),
                )
        except Exception as e:
            logger.debug("AD-536: Promotion request failed: %s", e)
        return None

    def _route_promotion_approval(self, criticality: str) -> str:
        """AD-536: Determine approver callsign based on criticality."""
        from probos.config import PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD

        captain_levels = {"high", "critical"}
        if PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD == "high":
            captain_levels = {"high", "critical"}
        elif PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD == "critical":
            captain_levels = {"critical"}

        if criticality in captain_levels:
            return "captain"

        # LOW/MEDIUM → department chief
        agent_type = getattr(self, "agent_type", "")
        _rt = getattr(self, "_runtime", None)
        department = ""
        if _rt and hasattr(_rt, "ontology") and _rt.ontology:
            department = _rt.ontology.get_agent_department(agent_type) or ""
        return self._DEPARTMENT_CHIEFS.get(department, "captain")

    async def _announce_promotion_request(
        self, procedure_id: str, promotion_result: dict
    ) -> None:
        """AD-536: Post promotion request to Ward Room and DM the approver."""
        _rt = getattr(self, "_runtime", None)
        if not _rt or not hasattr(_rt, "ward_room") or not _rt.ward_room:
            return

        criticality = promotion_result.get("criticality", "low")
        approver = self._route_promotion_approval(criticality)
        quality = promotion_result.get("quality_metrics", {})
        proc_name = promotion_result.get("procedure_name", procedure_id[:8])
        intent_types = promotion_result.get("intent_types", [])

        body = (
            f"**Procedure Promotion Request**\n\n"
            f"**Procedure:** {proc_name}\n"
            f"**Intent Types:** {', '.join(intent_types) if intent_types else 'general'}\n"
            f"**Description:** {promotion_result.get('procedure_description', 'N/A')}\n"
            f"**Compilation Level:** {promotion_result.get('compilation_level', 0)}\n"
            f"**Quality:** {quality.get('effective_rate', 0):.0%} effective over "
            f"{quality.get('total_completions', 0)} completions\n"
            f"**Criticality:** {criticality}\n"
            f"**Recommended Approver:** @{approver}\n\n"
            f"Use `procedure approve {procedure_id}` to approve."
        )

        try:
            agent_type = getattr(self, "agent_type", "")
            agent_id = getattr(self, "_agent_id", agent_type)
            callsign = getattr(self, "_callsign", agent_type)

            # Post to appropriate channel
            department = ""
            if _rt.ontology:
                department = _rt.ontology.get_agent_department(agent_type) or ""

            channels = await _rt.ward_room.list_channels()
            target_channel = None
            # Critical → Bridge/All Hands, routine → department channel
            chan_name = "All Hands" if criticality in ("high", "critical") else (department or "All Hands")
            for ch in channels:
                if ch.name == chan_name:
                    target_channel = ch
                    break
            if not target_channel and channels:
                target_channel = channels[0]

            if target_channel:
                await _rt.ward_room.create_thread(
                    channel_id=target_channel.id,
                    author_id=agent_id,
                    title=f"[Promotion Request] {proc_name}",
                    body=body,
                    author_callsign=callsign,
                )

            # DM the approver
            approver_id = approver
            dm_body = (
                f"Procedure promotion request requires your review: {proc_name}. "
                f"Quality: {quality.get('effective_rate', 0):.0%} effective over "
                f"{quality.get('total_completions', 0)} completions. "
                f"Criticality: {criticality}. Use `procedure approve {procedure_id}` to approve."
            )
            try:
                dm_channel = await _rt.ward_room.get_or_create_dm_channel(
                    agent_id, approver_id,
                    callsign_a=callsign, callsign_b=approver,
                )
                await _rt.ward_room.create_thread(
                    channel_id=dm_channel.id,
                    author_id=agent_id,
                    title=f"Promotion Review: {proc_name}",
                    body=dm_body,
                    author_callsign=callsign,
                )
            except Exception:
                logger.debug("AD-536: Failed to DM approver %s", approver)

        except Exception as e:
            logger.debug("AD-536: Ward Room announcement failed: %s", e)

    # ------------------------------------------------------------------
    # AD-537: Teaching Protocol
    # ------------------------------------------------------------------

    async def _teach_procedure(
        self,
        procedure_id: str,
        target_callsign: str,
    ) -> bool:
        """AD-537: Teach a Level 5 Expert procedure to another agent via Ward Room DM.

        Preconditions: Level 5, approved, Commander+ trust, target exists.
        Returns True on success.
        """
        from probos.config import TEACHING_MIN_COMPILATION_LEVEL, TEACHING_MIN_TRUST

        _store = self._procedure_store
        if not _store:
            logger.debug("AD-537: No procedure store available for teaching")
            return False

        # 1. Procedure exists
        procedure = await _store.get(procedure_id)
        if not procedure:
            logger.debug("AD-537: Procedure %s not found", procedure_id)
            return False

        # 2. Must be Level 5 Expert
        if procedure.compilation_level < TEACHING_MIN_COMPILATION_LEVEL:
            logger.debug(
                "AD-537: Procedure %s at level %d, need %d to teach",
                procedure_id[:8], procedure.compilation_level,
                TEACHING_MIN_COMPILATION_LEVEL,
            )
            return False

        # 3. Must be institutionally approved
        promotion_status = await _store.get_promotion_status(procedure_id)
        if promotion_status != "approved":
            logger.debug("AD-537: Procedure %s not approved (status: %s)", procedure_id[:8], promotion_status)
            return False

        # 4. Agent trust must be Commander+
        _rt = getattr(self, "_runtime", None)
        agent_type = getattr(self, "agent_type", "")
        trust_score = 0.5
        if _rt and hasattr(_rt, "trust_network") and _rt.trust_network:
            trust_score = _rt.trust_network.get_score(agent_type)
        if trust_score < TEACHING_MIN_TRUST:
            logger.debug("AD-537: Trust %.2f below teaching threshold %.2f", trust_score, TEACHING_MIN_TRUST)
            return False

        # 5. Ward Room available
        if not _rt or not hasattr(_rt, "ward_room") or not _rt.ward_room:
            logger.debug("AD-537: Ward Room not available for teaching")
            return False

        # 6. Format teaching message
        quality = await _store.get_quality_metrics(procedure_id)
        total_comp = quality.get("total_completions", 0) if quality else 0
        effective_rate = quality.get("effective_rate", 0) if quality else 0
        steps_text = "\n".join(f"  {s.step_number}. {s.action}" for s in procedure.steps)
        preconditions_text = "\n".join(f"  - {p}" for p in procedure.preconditions) if procedure.preconditions else "  (none)"
        postconditions_text = "\n".join(f"  - {p}" for p in procedure.postconditions) if procedure.postconditions else "  (none)"

        callsign = getattr(self, "_callsign", agent_type)
        agent_id = getattr(self, "_agent_id", agent_type)

        body = (
            f"**[TEACHING] Procedure: {procedure.name}**\n\n"
            f"I'm teaching you this procedure because I've validated it through "
            f"{total_comp} successful executions with {effective_rate:.0%} success rate.\n\n"
            f"**Description:** {procedure.description}\n\n"
            f"**Steps:**\n{steps_text}\n\n"
            f"**Preconditions:**\n{preconditions_text}\n\n"
            f"**Postconditions:**\n{postconditions_text}\n\n"
            f"This procedure has been institutionally approved and promoted to Expert level."
        )

        # 7. Send DM
        try:
            dm_channel = await _rt.ward_room.get_or_create_dm_channel(
                agent_id, target_callsign,
                callsign_a=callsign, callsign_b=target_callsign,
            )
            await _rt.ward_room.create_thread(
                channel_id=dm_channel.id,
                author_id=agent_id,
                title=f"[TEACHING] {procedure.name}",
                body=body,
                author_callsign=callsign,
            )
            logger.info(
                "AD-537: Taught procedure '%s' to %s",
                procedure.name, target_callsign,
            )
            return True
        except Exception as e:
            logger.debug("AD-537: Teaching DM failed: %s", e)
            return False

    async def perceive(self, intent: Any) -> dict:
        """Package the intent as an observation for the LLM.

        AD-492: Generates a correlation_id at perception time to thread
        through the entire cognitive cycle (decide → act → episode → post).
        """
        # AD-492: Generate correlation ID for this cognitive cycle
        correlation_id = uuid.uuid4().hex[:12]
        self._current_correlation_id = correlation_id

        if isinstance(intent, IntentMessage):
            observation = {
                "intent": intent.intent,
                "params": intent.params,
                "context": intent.context,
                "intent_id": intent.id,  # AD-432: Preserve for journal traceability
                "correlation_id": correlation_id,  # AD-492
            }
        else:
            # Dict fallback (for compatibility with BaseAgent contract)
            observation = {
                "intent": intent.get("intent", "unknown") if isinstance(intent, dict) else "unknown",
                "params": intent.get("params", {}) if isinstance(intent, dict) else {},
                "context": intent.get("context", "") if isinstance(intent, dict) else "",
                "correlation_id": correlation_id,  # AD-492
            }

        # AD-492: Store correlation_id on working memory for cross-reference
        _wm = getattr(self, '_working_memory', None)
        if _wm:
            _wm.set_correlation_id(correlation_id)

        return observation

    def _compose_dm_instructions(self, brief: bool = False) -> str:
        """Build DM instruction block with department-grouped roster (BF-051/052)."""
        _rt = getattr(self, '_runtime', None)
        if not _rt:
            return ""

        # Build department-grouped roster
        _dm_crew_list = ""
        if hasattr(_rt, 'callsign_registry') and hasattr(_rt, 'ontology') and _rt.ontology:
            try:
                _all_cs = _rt.callsign_registry.all_callsigns()
                _self_atype = getattr(self, 'agent_type', '')
                dept_groups: dict[str, list[str]] = {}
                for atype, cs in _all_cs.items():
                    if atype == _self_atype or not cs:
                        continue
                    dept_id = _rt.ontology.get_agent_department(atype)
                    dept_name = (dept_id or "bridge").capitalize()
                    dept_groups.setdefault(dept_name, []).append(f"@{cs}")
                if dept_groups:
                    parts = []
                    for dn in sorted(dept_groups):
                        members = ", ".join(sorted(dept_groups[dn]))
                        parts.append(f"{dn}: {members}")
                    _dm_crew_list = "Available crew to DM:\n" + "\n".join(parts) + "\n"
            except Exception:
                logger.debug("Cognitive agent context failed", exc_info=True)
                try:
                    _all_cs = _rt.callsign_registry.all_callsigns()
                    _self_atype = getattr(self, 'agent_type', '')
                    _crew_entries = [f"@{cs}" for atype, cs in _all_cs.items()
                                     if atype != _self_atype and cs]
                    if _crew_entries:
                        _dm_crew_list = f"Available crew to DM: {', '.join(sorted(_crew_entries))}\n"
                except Exception:
                    logger.debug("Crew list building failed", exc_info=True)
        elif hasattr(_rt, 'callsign_registry'):
            try:
                _all_cs = _rt.callsign_registry.all_callsigns()
                _self_atype = getattr(self, 'agent_type', '')
                _crew_entries = [f"@{cs}" for atype, cs in _all_cs.items()
                                 if atype != _self_atype and cs]
                if _crew_entries:
                    _dm_crew_list = f"Available crew to DM: {', '.join(sorted(_crew_entries))}\n"
            except Exception:
                logger.debug("Crew list building failed", exc_info=True)

        if brief:
            return (
                "\n\nYou may also send a private message to a crew member:\n"
                "[DM @callsign]\nYour message (2-3 sentences).\n[/DM]\n"
                f"{_dm_crew_list}"
                "ONLY DM crew listed above. You may DM @captain for urgent matters.\n"
            )

        return (
            "**Direct message a crew member** — reach out privately to another agent:\n"
            "[DM @callsign]\n"
            "Your message to this crew member (2-3 sentences).\n"
            "[/DM]\n"
            f"{_dm_crew_list}"
            "Use for: consulting a specialist, coordinating on a shared concern, "
            "asking for input on something in your department. "
            "ONLY DM crew members listed above. Do NOT invent crew members who don't exist. "
            "You may DM @captain for urgent matters that need the Captain's direct attention. "
            "Use sparingly — routine reports belong in your observation post.\n\n"
        )

    async def decide(self, observation: dict) -> dict:
        """Consult the LLM with instructions + observation.

        Decision Distillation (AD-272): checks in-memory cache before
        calling LLM. Cache hits return instantly (<1ms, $0).
        """
        if not self._llm_client:
            return {"action": "error", "reason": "No LLM client available"}

        # --- Decision cache lookup ---
        cache = _DECISION_CACHES.setdefault(self.agent_type, {})
        cache_key = self._compute_cache_key(observation)

        if cache_key in cache:
            decision, created_at, ttl = cache[cache_key]
            if time.monotonic() - created_at < ttl:
                _CACHE_HITS[self.agent_type] = _CACHE_HITS.get(self.agent_type, 0) + 1
                logger.debug("Decision cache hit for %s (key=%s)", self.agent_type, cache_key[:8])
                # AD-431: Journal cache hits too (for token accounting accuracy)
                if self._cognitive_journal:
                    try:
                        import uuid as _uuid
                        await self._cognitive_journal.record(
                            entry_id=_uuid.uuid4().hex,
                            timestamp=time.time(),
                            agent_id=self.id,
                            agent_type=self.agent_type,
                            intent=observation.get("intent", ""),
                            intent_id=observation.get("intent_id", ""),
                            cached=True,
                            correlation_id=observation.get("correlation_id", ""),
                        )
                    except Exception:
                        logger.debug("Journal recording failed", exc_info=True)
                return {**decision, "cached": True}
            else:
                del cache[cache_key]

        _CACHE_MISSES[self.agent_type] = _CACHE_MISSES.get(self.agent_type, 0) + 1

        # AD-573: Per-cycle memory budget tracking
        _budget_mgr: MemoryBudgetManager | None = None
        memory_budget_config = getattr(self, "_memory_budget_config", None)
        if memory_budget_config and memory_budget_config.enabled:
            from probos.cognitive.memory_budget import MemoryBudgetManager
            _budget_mgr = MemoryBudgetManager(memory_budget_config)

        # AD-595e: Inject qualification standing (after cache key, before LLM call)
        await self._refresh_qualification_standing()
        if getattr(self, '_qualification_standing', None):
            observation["qualification_standing"] = self._qualification_standing

        # --- AD-534: Procedural memory check (semantic match) ---
        procedural_result = await self._check_procedural_memory(observation)
        if procedural_result is not None:
            # Record in journal (fire-and-forget)
            if self._cognitive_journal:
                try:
                    import uuid as _uuid
                    await self._cognitive_journal.record(
                        entry_id=_uuid.uuid4().hex,
                        timestamp=time.time(),
                        agent_id=self.id,
                        agent_type=self.agent_type,
                        intent=observation.get("intent", ""),
                        intent_id=observation.get("intent_id", ""),
                        cached=True,
                        total_tokens=0,
                        procedure_id=procedural_result.get("procedure_id", ""),
                        correlation_id=observation.get("correlation_id", ""),
                    )
                except Exception:
                    logger.debug("Journal recording failed", exc_info=True)
            return procedural_result

        # --- AD-643a: Intent-driven chain activation with targeted skill loading ---
        # Priority 1: externally-set chain (escape hatch for skills, JIT, etc.)
        if self._pending_sub_task_chain is not None:
            chain = self._pending_sub_task_chain
            self._pending_sub_task_chain = None  # consume once
            # External chains get all augmentation skills (pre-AD-643 behavior)
            if observation.get("intent") in _CHAIN_ELIGIBLE_INTENTS:
                _aug = self._load_augmentation_skills(observation.get("intent", ""))
                if _aug:
                    observation["_augmentation_skill_instructions"] = _aug
            logger.info(
                "AD-632f: External chain activated for %s (intent=%s, source=%s)",
                self.agent_type,
                observation.get("intent", ""),
                getattr(chain, "source", "unknown"),
            )
            chain_result = await self._execute_sub_task_chain(chain, observation)
            if chain_result is not None:
                _cache_ttl = self._get_cache_ttl()
                cache[cache_key] = (chain_result, time.monotonic(), _cache_ttl)
                return chain_result
            logger.info("AD-632f: Falling back to single-call for %s", self.agent_type)

        # Priority 2: intent-driven routing (AD-643a)
        elif self._should_activate_chain(observation):
            chain_result = await self._execute_chain_with_intent_routing(observation)
            if chain_result is not None:
                _cache_ttl = self._get_cache_ttl()
                cache[cache_key] = (chain_result, time.monotonic(), _cache_ttl)
                return chain_result
            # chain_result is None → fall through to _decide_via_llm()
            # Skills may already be loaded in observation from intent routing

        # --- LLM call (cache miss) ---
        decision = await self._decide_via_llm(observation)

        # Record strategy outcomes (AD-384)
        applied_strategy_ids = decision.pop("_applied_strategy_ids", [])
        if applied_strategy_ids and self._strategy_advisor:
            for sid in applied_strategy_ids:
                self._strategy_advisor.record_outcome(
                    sid, self.agent_type, success=True
                )

        # --- Store in cache ---
        ttl = self._get_cache_ttl()
        cache[cache_key] = (decision, time.monotonic(), ttl)

        # Evict oldest entry if cache exceeds 1000 per agent type
        if len(cache) > 1000:
            oldest_key = min(cache, key=lambda k: cache[k][1])
            del cache[oldest_key]

        return decision

    async def _decide_via_llm(self, observation: dict) -> dict:
        """AD-534b: LLM-only decision path — extracted from decide() for DRY reuse.

        Builds messages, calls LLM, records to journal.
        Returns decision dict. Does NOT check decision cache or procedural memory.
        """
        # AD-626: Load augmentation skills BEFORE building user message
        # so _build_user_message() can frame tasks with skill instructions.
        # Skip if already loaded by decide() for chain activation (AD-632f).
        if "_augmentation_skill_instructions" not in observation:
            _aug_instructions = self._load_augmentation_skills(observation.get("intent", ""))
            if _aug_instructions:
                observation["_augmentation_skill_instructions"] = _aug_instructions

        # AD-585: Tiered knowledge loading (ambient + contextual).
        _knowledge_loader = getattr(self, "_knowledge_loader", None)
        if _knowledge_loader:
            try:
                _ambient = await _knowledge_loader.load_ambient()
                if _ambient:
                    observation.setdefault("_knowledge_ambient", _ambient)

                _intent_type = observation.get("intent", "")
                if _intent_type:
                    _department = observation.get("department", "")
                    _contextual = await _knowledge_loader.load_contextual(
                        _intent_type,
                        _department,
                    )
                    if _contextual:
                        observation.setdefault("_knowledge_contextual", _contextual)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "AD-585: Knowledge loading failed for agent_type=%s; proceeding without. "
                    "Agent will use base context only.",
                    self.agent_type,
                    exc_info=True,
                )

        user_message = await self._build_user_message(observation)

        # Strategy advice (AD-384)
        applied_strategy_ids: list[str] = []
        if self._strategy_advisor:
            intent_type = observation.get("intent", "")
            if intent_type:
                strategies = self._strategy_advisor.query_strategies(
                    intent_type, self.agent_type
                )
                context = self._strategy_advisor.format_for_context(strategies)
                if context:
                    user_message = user_message + "\n\n" + context
                applied_strategy_ids = [
                    s["id"] for s in strategies if s.get("id")
                ]

        from probos.cognitive.standing_orders import compose_instructions

        # BF-010: conversational system prompt for 1:1 sessions
        # AD-407b: conversational system prompt for ward room notifications
        is_conversation = observation.get("intent") in ("direct_message", "ward_room_notification", "proactive_think")

        # AD-586: Classify current task for contextual standing orders
        _task_type = None
        if self._task_context is not None:
            intent_name = observation.get("intent", "")
            _task_type = self._task_context.classify_task(intent_name)

        if is_conversation:
            # For 1:1 and ward room, use personality + standing orders only.
            # Exclude domain-specific task instructions (report formats, output blocks)
            # so the LLM responds naturally as itself.
            composed = compose_instructions(
                agent_type=getattr(self, "agent_type", self.__class__.__name__.lower()),
                hardcoded_instructions="",
                callsign=self._resolve_callsign(),
                agent_rank=getattr(self, "rank", None),  # AD-596b
                skill_profile=getattr(self, '_skill_profile', None),  # AD-625
                task_type=_task_type,
            )
            if observation.get("intent") == "ward_room_notification":
                composed += (
                    "\n\nYou are participating in the Ward Room — the ship's discussion forum. "
                    "Write concise, conversational posts (2-4 sentences). "
                    "Speak in your natural voice. Don't be formal unless the topic demands it. "
                    "You may be responding to the Captain or to a fellow crew member. "
                    "Engage naturally — agree, disagree, build on ideas, ask questions. "
                    "Do NOT repeat what someone else already said. "
                    "If you have nothing meaningful to add, respond with exactly: [NO_RESPONSE]"
                    "\n\nAfter your reply (or [NO_RESPONSE]), you may endorse posts you've read in this thread. "
                    "If a post is particularly insightful, actionable, or well-reasoned, endorse it up. "
                    "If a post is incorrect, misleading, or unhelpful, endorse it down. "
                    "Only endorse when you have a clear opinion — not every post needs a vote. "
                    "Use this format, one per line:\n"
                    "[ENDORSE post_id UP]\n"
                    "[ENDORSE post_id DOWN]\n"
                    "Place endorsements AFTER your reply text, each on its own line. "
                    "Do NOT endorse your own posts."
                )
                # BF-051: DM syntax available in ward room context too
                _dm_instr = self._compose_dm_instructions(brief=True)
                if _dm_instr:
                    composed += _dm_instr
            elif observation.get("intent") == "proactive_think":
                composed += (
                    "\n\nYou are reviewing recent ship activity during a quiet moment. "
                    "If you notice something noteworthy — a pattern, a concern, an insight "
                    "related to your expertise — compose a brief observation (2-4 sentences). "
                    "This will be posted to the Ward Room as a new thread. "
                    "Speak in your natural voice. Be specific and actionable. "
                    "If nothing warrants attention right now, respond with exactly: [NO_RESPONSE]\n"
                    "Keep game-related discussions (tic-tac-toe, game strategy, match commentary) "
                    "in the Recreation channel using [REPLY] to existing game threads. "
                    "Your department channel is for professional observations related to your role."
                    "\n\nIf you identify a concrete, actionable improvement to the ship's systems "
                    "(not a vague observation), propose it using:\n"
                    "[PROPOSAL]\n"
                    "Title: <short title>\n"
                    "Rationale: <why this matters and what it would improve>\n"
                    "Affected Systems: <comma-separated subsystems>\n"
                    "Priority: low|medium|high\n"
                    "[/PROPOSAL]\n"
                    "Only propose improvements you have evidence for — not speculation. "
                    "Reserve proposals for genuine insights.\n"
                    "IMPORTANT: If you recently participated in a discussion that identified a system "
                    "problem, diagnosed a root cause, or suggested an improvement — and no formal "
                    "improvement proposal has been submitted for it yet — you should submit one now. "
                    "Collaborative diagnosis should culminate in a formal proposal so the Captain "
                    "can track and act on the finding."
                    "\n\n## Available Actions\n"
                    "Beyond posting observations, you can take structured actions on Ward Room content. "
                    "Place action tags AFTER your observation text, each on its own line.\n\n"
                    "**Endorse posts** — signal agreement or disagreement with a post:\n"
                    "[ENDORSE post_id UP]\n"
                    "[ENDORSE post_id DOWN]\n"
                    "Only endorse when you have a clear, justified opinion. Do NOT endorse your own posts.\n\n"
                    "**Reply to threads** — contribute to an existing discussion instead of starting a new one:\n"
                    "[REPLY thread_id]\n"
                    "Your reply text here (2-3 sentences).\n"
                    "[/REPLY]\n"
                    "Reply when you have something to ADD to an existing conversation. "
                    "Do not reply just to agree — use endorsement for that. "
                    "Replies require Lieutenant rank or higher.\n\n"
                    "**Notebook entries** — document extended analysis in Ship's Records:\n"
                    "[NOTEBOOK topic-slug]\n"
                    "Your extended analysis, research findings, or diagnostic report here.\n"
                    "[/NOTEBOOK]\n"
                    "Use for: research findings, pattern analysis, baseline readings, diagnostic reports. "
                    "This writes to your personal notebook in Ship's Records (AD-434).\n\n"
                )
                composed += self._compose_dm_instructions()

                # AD-526a: Challenge action (all ranks)
                composed += (
                    "**Challenge a crewmate** — initiate a game in the Recreation channel:\n"
                    "[CHALLENGE @callsign tictactoe]\n"
                    "Challenge when the mood is light and you want to build social bonds. "
                    "If no one has played a game recently, consider initiating one — "
                    "recreation strengthens crew cohesion. "
                    "Do NOT challenge during alert conditions or critical situations.\n\n"
                    "**Make a game move** — play your turn in an active game:\n"
                    "[MOVE position]\n"
                    "Position is game-specific (e.g. 0-8 for tic-tac-toe). "
                    "Only respond with a move when it's your turn.\n\n"
                )

                composed += (
                    "**When to act vs. observe:**\n"
                    "- See a good post? → [ENDORSE post_id UP] (not a reply saying 'good point')\n"
                    "- Have a concrete addition? → [REPLY thread_id] with your contribution\n"
                    "- Need specialist input? → [DM @callsign] with your question\n"
                    "- Detailed analysis warranted? → [NOTEBOOK topic-slug] with your findings\n"
                    "- See something new? → Write an observation (new thread)\n"
                    "- Nothing noteworthy? → [NO_RESPONSE]"
                )

            else:
                composed += (
                    "\n\nYou are in a 1:1 conversation with the Captain. "
                    "Respond naturally and conversationally as yourself. "
                    "Do NOT use any structured output formats, report blocks, "
                    "code blocks, or task-specific templates. "
                    "Be genuine, personable, and engage with what the Captain says. "
                    "Draw on your expertise and personality, but keep it conversational."
                )

                # AD-572/573: If agent has an active game, add [MOVE] instruction
                if getattr(self, '_working_memory', None) and self._working_memory.has_engagement("game"):
                    composed += (
                        "\n\nYou are currently in an active game. "
                        "If the Captain asks you to make a move or you decide to play, "
                        "include [MOVE position] in your response (e.g. [MOVE 4]). "
                        "The move will be executed automatically. "
                        "You can still chat naturally — the move tag can appear "
                        "anywhere in your response alongside your conversational text."
                    )
        else:
            composed = compose_instructions(
                agent_type=getattr(self, "agent_type", self.__class__.__name__.lower()),
                hardcoded_instructions=self.instructions or "",
                callsign=self._resolve_callsign(),
                agent_rank=getattr(self, "rank", None),  # AD-596b
                skill_profile=getattr(self, '_skill_profile', None),  # AD-625
                task_type=_task_type,
            )

        # AD-596b: Append cognitive skill instructions when activated
        _skill_instr = observation.get("cognitive_skill_instructions")
        if _skill_instr:
            composed += f"\n\n---\n\n## Active Skill: {observation.get('cognitive_skill_name', 'Unknown')}\n\n{_skill_instr}"

        request = LLMRequest(
            prompt=user_message,
            system_prompt=composed,
            tier=self._resolve_tier(),
        )

        # AD-431: Time the LLM call for journal
        _t0 = time.monotonic()
        # AD-637f: Unified priority classification
        _params = observation.get("params", {})
        _priority = Priority.classify(
            intent=observation.get("intent", ""),
            is_captain=_params.get("author_id", "") == "captain",
            was_mentioned=_params.get("was_mentioned", False),
        )
        response = await self._llm_client.complete(request, priority=_priority)
        _latency_ms = (time.monotonic() - _t0) * 1000

        decision = {
            "action": "execute",
            "llm_output": response.content,
            "tier_used": response.tier,
        }

        # AD-431: Record to Cognitive Journal (fire-and-forget)
        if self._cognitive_journal:
            try:
                _prompt_hash = hashlib.md5(user_message[:500].encode()).hexdigest()[:12]
                await self._cognitive_journal.record(
                    entry_id=request.id,
                    timestamp=time.time(),
                    agent_id=self.id,
                    agent_type=self.agent_type,
                    tier=response.tier,
                    model=response.model,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    total_tokens=response.tokens_used,
                    latency_ms=_latency_ms,
                    intent=observation.get("intent", ""),
                    success=response.error is None,
                    cached=False,
                    request_id=request.id,
                    prompt_hash=_prompt_hash,
                    response_length=len(response.content),
                    intent_id=observation.get("intent_id", ""),
                    response_hash=hashlib.md5(response.content[:500].encode()).hexdigest()[:12],
                    correlation_id=observation.get("correlation_id", ""),
                )
            except Exception:
                logger.debug("Journal recording failed", exc_info=True)  # Non-critical — never block agent cognition

        # Pass strategy IDs back for caller to process
        if applied_strategy_ids:
            decision["_applied_strategy_ids"] = applied_strategy_ids

        return decision

    async def _run_llm_fallback(self, observation: dict[str, Any]) -> dict[str, Any] | None:
        """AD-534b: Re-run through LLM path, skipping procedural memory and decision cache."""
        try:
            return await self._decide_via_llm(observation)
        except Exception:
            logger.debug("LLM fallback decision failed", exc_info=True)
            return None

    # --- AD-632f: Chain activation trigger methods ---

    def _should_activate_chain(self, observation: dict) -> bool:
        """AD-632f: Evaluate whether this observation warrants a multi-step chain.

        Gates (evaluated in order, first failure short-circuits):
          0. Executor exists and is enabled
          1. Intent type is in _CHAIN_ELIGIBLE_INTENTS
        """
        # Gate 0: executor readiness
        if self._sub_task_executor is None:
            return False
        if not self._sub_task_executor.enabled:
            return False
        # Gate 1: intent type filter
        intent = observation.get("intent", "")
        if intent not in _CHAIN_ELIGIBLE_INTENTS:
            logger.debug(
                "AD-632f: Chain skipped for %s (intent=%s not eligible)",
                self.agent_type, intent,
            )
            return False
        return True

    @staticmethod
    def _extract_intended_actions(chain_results: list) -> list[str]:
        """AD-643a: Extract intended_actions from ANALYZE step results.

        Returns normalized list of action tags, or empty list if not found.
        Handles: list, comma-separated string, single string.
        """
        from probos.cognitive.sub_task import SubTaskType
        for r in reversed(chain_results):
            if r.sub_task_type == SubTaskType.ANALYZE and r.success and r.result:
                raw = r.result.get("intended_actions")
                if raw is None:
                    return []
                if isinstance(raw, list):
                    return [str(a).strip().lower() for a in raw if str(a).strip()]
                if isinstance(raw, str):
                    # Handle comma-separated or single value
                    if "," in raw:
                        return [a.strip().lower() for a in raw.split(",") if a.strip()]
                    stripped = raw.strip().lower()
                    return [stripped] if stripped else []
                return []
        return []

    @staticmethod
    def _detect_undeclared_actions(
        compose_output: str,
        intended_actions: list[str],
    ) -> list[str]:
        """AD-643b: Detect actions in COMPOSE output not declared in intended_actions.

        Scans for known action markers and returns undeclared action tags.
        Patterns match the markers used by proactive.py action extraction.
        """
        if not compose_output:
            return []

        declared = set(intended_actions)
        undeclared = []

        markers = {
            "notebook": re.compile(r'\[NOTEBOOK\s', re.IGNORECASE),
            "endorse": re.compile(r'\[ENDORSE\s', re.IGNORECASE),
            "proposal": re.compile(r'\[PROPOSAL\]', re.IGNORECASE),
            "dm": re.compile(r'\[DM\s', re.IGNORECASE),
            "ward_room_reply": re.compile(r'\[REPLY\s', re.IGNORECASE),
        }

        for action_tag, pattern in markers.items():
            if action_tag not in declared and pattern.search(compose_output):
                undeclared.append(action_tag)

        return undeclared

    def _build_chain_for_intent(self, observation: dict):
        """AD-632f: Build a SubTaskChain for the given intent type.

        Returns SubTaskChain or None (unknown intent → single-call fallback).
        """
        from probos.cognitive.sub_task import SubTaskChain, SubTaskSpec, SubTaskType

        intent = observation.get("intent", "")

        if intent == "ward_room_notification":
            return SubTaskChain(
                steps=[
                    SubTaskSpec(
                        sub_task_type=SubTaskType.QUERY,
                        name="query-thread-context",
                        context_keys=("thread_metadata", "credibility", "self_monitoring", "introspective_telemetry"),
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.ANALYZE,
                        name="analyze-thread",
                        prompt_template="thread_analysis",
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.COMPOSE,
                        name="compose-reply",
                        prompt_template="ward_room_response",
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.EVALUATE,
                        name="evaluate-reply",
                        prompt_template="ward_room_quality",
                        required=False,
                        depends_on=("compose-reply",),
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.REFLECT,
                        name="reflect-reply",
                        prompt_template="ward_room_reflection",
                        required=False,
                        depends_on=("compose-reply", "evaluate-reply"),  # BF-206
                    ),
                ],
                source="intent_trigger:ward_room_notification",
            )

        if intent == "proactive_think":
            return SubTaskChain(
                steps=[
                    SubTaskSpec(
                        sub_task_type=SubTaskType.QUERY,
                        name="query-situation",
                        context_keys=("unread_counts", "trust_score"),
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.ANALYZE,
                        name="analyze-situation",
                        prompt_template="situation_review",
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.COMPOSE,
                        name="compose-observation",
                        prompt_template="proactive_observation",
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.EVALUATE,
                        name="evaluate-observation",
                        prompt_template="proactive_quality",
                        required=False,
                        depends_on=("compose-observation",),
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.REFLECT,
                        name="reflect-observation",
                        prompt_template="proactive_reflection",
                        required=False,
                        depends_on=("compose-observation", "evaluate-observation"),  # BF-206
                    ),
                ],
                source="intent_trigger:proactive_think",
            )

        return None

    async def _execute_sub_task_chain(
        self,
        chain,
        observation: dict,
    ) -> dict | None:
        """AD-632a: Execute a sub-task chain, falling back to None on failure.

        Returns a decision dict if the chain completes successfully, or None
        to signal the caller to fall through to single-call _decide_via_llm().
        """
        if self._sub_task_executor is None:
            return None
        if not self._sub_task_executor.can_execute(chain):
            return None

        # AD-632c: Inject agent identity into context for handler access
        observation["_agent_id"] = self.id
        observation["_agent_type"] = self.agent_type
        observation["_callsign"] = getattr(self, 'callsign', self.agent_type)
        _dept = getattr(self, 'department', None)
        if _dept is None:
            from probos.cognitive.standing_orders import get_department
            _dept = get_department(self.agent_type) or "unassigned"
        observation["_department"] = _dept

        # BF-184: Social obligation flags for evaluate/reflect bypass
        _params = observation.get("params", {})
        observation["_from_captain"] = _params.get("author_id", "") == "captain"
        observation["_was_mentioned"] = _params.get("was_mentioned", False)

        # BF-187: DM social obligation — DM recipients must always respond
        observation["_is_dm"] = _params.get("is_dm_channel", False)

        # AD-638: Boot camp quality gate relaxation
        _rt = getattr(self, '_runtime', None)
        if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.is_enrolled(self.id):
            observation["_boot_camp_active"] = True

        # AD-639: Trust-adaptive chain personality tuning
        if not observation.get("_boot_camp_active"):
            _chain_cfg = getattr(getattr(_rt, 'config', None), 'chain_tuning', None) if _rt else None
            if _chain_cfg and _chain_cfg.enabled:
                _agent_type = getattr(self, "agent_type", "")
                _trust = 0.5
                if _rt and hasattr(_rt, "trust_network") and _rt.trust_network:
                    _trust = _rt.trust_network.get_score(_agent_type)
                observation["_trust_score"] = _trust
                if _trust < _chain_cfg.low_trust_ceiling:
                    observation["_chain_trust_band"] = "low"
                elif _trust >= _chain_cfg.high_trust_floor:
                    observation["_chain_trust_band"] = "high"
                else:
                    observation["_chain_trust_band"] = "mid"
                logger.debug(
                    "AD-639: %s trust=%.2f band=%s",
                    _agent_type, _trust, observation["_chain_trust_band"],
                )

        # AD-653: Wire event emission + agent identity for compose trust gates
        observation["_emit_event_fn"] = getattr(_rt, '_emit_event', None) if _rt else None
        observation["_agent_id"] = getattr(self, 'id', '') or getattr(self, 'agent_type', '')

        # BF-186: Thread rank, skill_profile, and crew manifest into chain context
        observation["_agent_rank"] = getattr(self, "rank", None)
        observation["_skill_profile"] = getattr(self, '_skill_profile', None)
        observation["_crew_manifest"] = self._compose_dm_instructions()

        # BF-189: Pre-format memories for chain handlers (AD-567b/568c/592 compliance)
        raw_memories = observation.get("recent_memories", [])
        if raw_memories and isinstance(raw_memories, list):
            source_framing = observation.get("_source_framing")
            formatted_lines = self._format_memory_section(raw_memories, source_framing=source_framing)
            observation["_formatted_memories"] = "\n".join(formatted_lines)
        else:
            observation["_formatted_memories"] = ""

        try:
            results = await self._sub_task_executor.execute(
                chain,
                observation,
                agent_id=self.id,
                agent_type=self.agent_type,
                intent=observation.get("intent", ""),
                intent_id=observation.get("intent_id", ""),
                journal=self._cognitive_journal,
            )
        except Exception as exc:
            import asyncio as _asyncio
            from probos.cognitive.sub_task import SubTaskError
            if isinstance(exc, (SubTaskError, _asyncio.TimeoutError)):
                logger.warning(
                    "AD-632a: Sub-task chain failed, falling back to single-call: %s",
                    exc,
                )
            else:
                logger.error(
                    "AD-632a: Unexpected error in sub-task chain: %s",
                    exc, exc_info=True,
                )
            return None

        # BF-206: Defense-in-depth — check Evaluate suppress before extracting output
        from probos.cognitive.sub_task import SubTaskType as _SubTaskType
        evaluate_results = [
            r for r in results
            if r.sub_task_type == _SubTaskType.EVALUATE and r.success and r.result
        ]
        for eval_r in evaluate_results:
            if eval_r.result.get("recommendation") == "suppress":
                rejection = eval_r.result.get("rejection_reason", "quality_gate")
                logger.info(
                    "BF-206: Chain output suppressed — Evaluate recommended suppress (%s)",
                    rejection,
                )
                # Emit confabulation suppressed event
                _rt = getattr(self, '_runtime', None)
                if _rt and hasattr(_rt, 'emit_event'):
                    from probos.events import EventType
                    _rt.emit_event(EventType.CONFABULATION_SUPPRESSED, {
                        "agent_id": self.id,
                        "agent_type": self.agent_type,
                        "callsign": getattr(self, 'callsign', self.agent_type),
                        "rejection_reason": rejection,
                        "intent": observation.get("intent", ""),
                        "trust_score": observation.get("_trust_score", 0.5),
                        "chain_trust_band": observation.get("_chain_trust_band", "unknown"),
                    })
                return {
                    "action": "execute",
                    "llm_output": "[NO_RESPONSE]",
                    "tier_used": "",
                    "sub_task_chain": True,
                    "chain_source": chain.source,
                    "chain_steps": len(chain.steps),
                    "_suppressed": True,
                    "_suppression_reason": rejection,
                    "_composition_brief": None,  # AD-645 Phase 3
                }

        # Construct decision from chain results — prefer REFLECT > COMPOSE > fallback
        from probos.cognitive.sub_task import SubTaskType
        reflect_results = [
            r for r in results
            if r.sub_task_type == SubTaskType.REFLECT and r.success
        ]
        compose_results = [
            r for r in results
            if r.sub_task_type == SubTaskType.COMPOSE and r.success
        ]
        if reflect_results:
            llm_output = reflect_results[-1].result.get("output", "")
            tier_used = reflect_results[-1].tier_used
        elif compose_results:
            llm_output = compose_results[-1].result.get("output", "")
            tier_used = compose_results[-1].tier_used
        else:
            # Concatenate all successful result outputs
            parts = [
                r.result.get("output", str(r.result))
                for r in results if r.success
            ]
            llm_output = "\n".join(parts)
            tier_used = results[-1].tier_used if results else ""

        # AD-645 Phase 3: Extract composition brief for metacognitive storage
        _composition_brief = None
        for r in results:
            if r.sub_task_type == SubTaskType.ANALYZE and r.success and r.result:
                _composition_brief = r.result.get("composition_brief")
                break

        return {
            "action": "execute",
            "llm_output": llm_output,
            "tier_used": tier_used,
            "sub_task_chain": True,
            "chain_source": chain.source,  # AD-632g: e.g., "intent_trigger:ward_room_notification"
            "chain_steps": len(chain.steps),  # AD-632g: step count for extraction
            "_composition_brief": _composition_brief,  # AD-645 Phase 3
        }

    async def _execute_chain_with_intent_routing(self, observation: dict) -> dict | None:
        """AD-643a: Two-phase chain execution with intent-driven skill loading.

        Phase 1 (Triage): QUERY + ANALYZE — no skills, determines intended_actions.
        Phase 2 (Execute): Load targeted skills, run remaining chain steps.

        Returns decision dict or None (fall through to _decide_via_llm).
        """
        from probos.cognitive.sub_task import SubTaskChain, SubTaskType

        intent = observation.get("intent", "")

        # --- Inject agent context (same keys as _execute_sub_task_chain) ---
        observation["_agent_id"] = self.id
        observation["_agent_type"] = self.agent_type
        observation["_callsign"] = getattr(self, 'callsign', self.agent_type)
        _dept = getattr(self, 'department', None)
        if _dept is None:
            from probos.cognitive.standing_orders import get_department
            _dept = get_department(self.agent_type) or "unassigned"
        observation["_department"] = _dept

        # BF-184: Social obligation flags
        _params = observation.get("params", {})
        observation["_from_captain"] = _params.get("author_id", "") == "captain"
        observation["_was_mentioned"] = _params.get("was_mentioned", False)
        observation["_is_dm"] = _params.get("is_dm_channel", False)

        # BF-210: Wire DM conversation partner for compose register adaptation
        if observation["_is_dm"]:
            observation["_dm_recipient"] = _params.get("author_callsign", "")

        # AD-649: Communication context for chain register adaptation
        _channel_name = _params.get("channel_name", "")
        _is_dm_channel = _params.get("is_dm_channel", False)
        observation["_communication_context"] = derive_communication_context(
            _channel_name, _is_dm_channel,
        )
        observation["_channel_name"] = _channel_name

        # AD-638: Boot camp quality gate relaxation
        _rt = getattr(self, '_runtime', None)
        if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.is_enrolled(self.id):
            observation["_boot_camp_active"] = True

        # AD-639: Trust-adaptive chain personality tuning
        if not observation.get("_boot_camp_active"):
            _chain_cfg = getattr(getattr(_rt, 'config', None), 'chain_tuning', None) if _rt else None
            if _chain_cfg and _chain_cfg.enabled:
                _agent_type = getattr(self, "agent_type", "")
                _trust = 0.5
                if _rt and hasattr(_rt, "trust_network") and _rt.trust_network:
                    _trust = _rt.trust_network.get_score(_agent_type)
                observation["_trust_score"] = _trust
                if _trust < _chain_cfg.low_trust_ceiling:
                    observation["_chain_trust_band"] = "low"
                elif _trust >= _chain_cfg.high_trust_floor:
                    observation["_chain_trust_band"] = "high"
                else:
                    observation["_chain_trust_band"] = "mid"

        # AD-653: Wire event emission + agent identity for compose trust gates
        observation["_emit_event_fn"] = getattr(_rt, '_emit_event', None) if _rt else None
        observation["_agent_id"] = getattr(self, 'id', '') or getattr(self, 'agent_type', '')

        # BF-186: Thread rank, skill_profile, crew manifest
        observation["_agent_rank"] = getattr(self, "rank", None)
        observation["_skill_profile"] = getattr(self, '_skill_profile', None)
        observation["_crew_manifest"] = self._compose_dm_instructions()

        # AD-644 Phase 1: Duty context for chain prompts
        _duty = _params.get("duty")
        if _duty:
            observation["_active_duty"] = _duty

        # AD-646: Universal cognitive baseline — always runs
        _context_parts = _params.get("context_parts", {})
        _cognitive_state = self._build_cognitive_state(_context_parts, observation=observation)
        observation.update(_cognitive_state)

        # AD-644 Phase 3: Situation awareness — environmental perception
        # Only runs when context_parts available (proactive path)
        _situation: dict[str, str] = {}
        if _context_parts:
            _situation = self._build_situation_awareness(_context_parts)
            observation.update(_situation)

        # AD-666: Sensorium budget tracking — observability, never blocks
        self._track_sensorium_budget(_cognitive_state, _situation)

        # BF-189: Pre-format memories
        raw_memories = observation.get("recent_memories", [])
        if raw_memories and isinstance(raw_memories, list):
            source_framing = observation.get("_source_framing")
            formatted_lines = self._format_memory_section(raw_memories, source_framing=source_framing)
            observation["_formatted_memories"] = "\n".join(formatted_lines)
        else:
            observation["_formatted_memories"] = ""

        # AD-643b: Inject eligible trigger awareness for ANALYZE prompt
        catalog = getattr(self, '_cognitive_skill_catalog', None)
        if catalog:
            _dept = observation.get("_department")
            _rank_val = observation.get("_agent_rank")
            if hasattr(_rank_val, 'value'):
                _rank_val = _rank_val.value
            eligible = catalog.get_eligible_triggers(
                department=_dept,
                agent_rank=_rank_val,
            )
            if eligible:
                observation["_eligible_triggers"] = eligible

        # --- Phase 1: Build and execute triage (QUERY + ANALYZE only) ---
        full_chain = self._build_chain_for_intent(observation)
        if full_chain is None:
            return None

        # Split chain: triage = QUERY + ANALYZE, execute = COMPOSE + EVALUATE + REFLECT
        triage_steps = [s for s in full_chain.steps if s.sub_task_type in (SubTaskType.QUERY, SubTaskType.ANALYZE)]
        execute_steps = [s for s in full_chain.steps if s.sub_task_type not in (SubTaskType.QUERY, SubTaskType.ANALYZE)]

        if not triage_steps:
            # No triage steps — fall back to full chain with all skills
            return None

        triage_chain = SubTaskChain(
            steps=triage_steps,
            chain_timeout_ms=full_chain.chain_timeout_ms,
            fallback=full_chain.fallback,
            source=f"{full_chain.source}:triage",
        )

        try:
            triage_results = await self._sub_task_executor.execute(
                triage_chain,
                observation,
                agent_id=self.id,
                agent_type=self.agent_type,
                intent=intent,
                intent_id=observation.get("intent_id", ""),
                journal=self._cognitive_journal,
            )
        except Exception as exc:
            logger.warning("AD-643a: Triage phase failed, falling back: %s", exc)
            return None

        # --- Extract intended_actions ---
        intended_actions = self._extract_intended_actions(triage_results)

        if not intended_actions:
            # ANALYZE didn't produce intended_actions — fall back to pre-AD-643 behavior
            logger.info("AD-643a: No intended_actions from ANALYZE, falling back to full chain")
            _aug = self._load_augmentation_skills(intent)
            if _aug:
                observation["_augmentation_skill_instructions"] = _aug
            # Re-execute full chain (triage results are lost — acceptable for fallback)
            return await self._execute_sub_task_chain(full_chain, observation)

        logger.info(
            "AD-643a: Agent %s intended_actions=%s (intent=%s)",
            self.agent_type, intended_actions, intent,
        )

        # --- Silent short-circuit ---
        if intended_actions == ["silent"]:
            logger.info("AD-643a: Silent intent — short-circuiting")
            return {
                "action": "execute",
                "llm_output": "[NO_RESPONSE]",
                "tier_used": "",
                "sub_task_chain": True,
                "chain_source": f"{full_chain.source}:silent",
                "chain_steps": len(triage_steps),
                "_composition_brief": None,  # AD-645 Phase 3
            }

        # --- Determine if communication chain should fire ---
        _COMM_ACTIONS = frozenset({"ward_room_post", "ward_room_reply", "endorse", "dm"})
        has_comm_action = bool(_COMM_ACTIONS.intersection(intended_actions))

        # --- Load targeted skills based on intended_actions ---
        catalog = getattr(self, '_cognitive_skill_catalog', None)
        if catalog:
            department = getattr(self, 'department', None)
            rank = getattr(self, 'rank', None)
            rank_val = rank.value if hasattr(rank, 'value') else rank
            entries = catalog.find_triggered_skills(
                intended_actions, intent,
                department=department, agent_rank=rank_val,
            )
            if entries:
                bridge = getattr(self, '_skill_bridge', None)
                profile = getattr(self, '_skill_profile', None)
                parts = []
                loaded_entries = []
                for entry in entries:
                    if bridge and not bridge.check_proficiency_gate(self.id, entry, profile):
                        continue
                    instructions = catalog.get_instructions(entry.name)
                    if instructions:
                        parts.append(instructions)
                        loaded_entries.append(entry)
                        logger.info(
                            "AD-643a: Loaded triggered skill '%s' for actions %s on %s",
                            entry.name, intended_actions, self.agent_type,
                        )
                if parts:
                    observation["_augmentation_skill_instructions"] = "".join(parts)
                self._augmentation_skills_used = loaded_entries
            else:
                self._augmentation_skills_used = []
        else:
            self._augmentation_skills_used = []

        # --- Phase 2: Execute remaining chain or fall through ---
        if has_comm_action and execute_steps:
            # Phase 2a: Execute full chain with skills loaded
            chain_result = await self._execute_sub_task_chain(full_chain, observation)

            # Phase 2b: Detect undeclared actions in compose output
            if chain_result and intended_actions:
                compose_text = chain_result.get("llm_output", "")
                undeclared = self._detect_undeclared_actions(compose_text, intended_actions)
                if undeclared:
                    # Find which skills would have loaded
                    missed_skills = []
                    if catalog:
                        for tag in undeclared:
                            triggered = catalog.find_triggered_skills(
                                [tag], intent,
                                department=department, agent_rank=rank_val,
                            )
                            missed_skills.extend(e.name for e in triggered)
                    missed_skills = list(set(missed_skills))

                    logger.info(
                        "AD-643b: %s took undeclared actions %s, missed skills %s",
                        self.agent_type, undeclared, missed_skills,
                    )

                    # Store feedback in observation for episode enrichment
                    observation["_undeclared_action_feedback"] = {
                        "undeclared_actions": undeclared,
                        "missed_skills": missed_skills,
                    }

                    # Provide compose output for re-reflect context
                    observation["_re_reflect_compose_output"] = compose_text

                    # Phase 2c: Re-reflect with feedback
                    chain_result = await self._re_reflect_with_feedback(
                        full_chain, observation, chain_result,
                    )

            return chain_result
        else:
            # Non-communication actions: fall through to _decide_via_llm()
            # Skills are already loaded in observation if any matched.
            logger.info(
                "AD-643a: No comm actions in %s — skipping chain, using single-call",
                intended_actions,
            )
            return None

    async def _re_reflect_with_feedback(
        self,
        full_chain,
        observation: dict,
        original_result: dict,
    ) -> dict:
        """AD-643b: Run a REFLECT-only chain with undeclared action feedback.

        After detecting undeclared actions in compose output, re-run REFLECT
        with feedback injected into the observation. The re-reflect output
        replaces the original chain result, ensuring the feedback flows into
        episodic memory via the reflection.

        Returns the updated decision dict (or original if re-reflect fails).
        """
        from probos.cognitive.sub_task import SubTaskChain, SubTaskType
        from dataclasses import replace as _dc_replace

        reflect_steps = [
            _dc_replace(s, depends_on=())
            for s in full_chain.steps
            if s.sub_task_type == SubTaskType.REFLECT
        ]
        if not reflect_steps:
            return original_result

        reflect_chain = SubTaskChain(
            steps=reflect_steps,
            chain_timeout_ms=30000,  # 30s — single step, generous timeout
            fallback="skip",
            source=f"{full_chain.source}:re_reflect",
        )

        try:
            reflect_results = await self._sub_task_executor.execute(
                reflect_chain,
                observation,
                agent_id=self.id,
                agent_type=self.agent_type,
                intent=observation.get("intent", ""),
                intent_id=observation.get("intent_id", ""),
                journal=self._cognitive_journal,
            )

            # Extract re-reflect output
            for r in reversed(reflect_results):
                if r.sub_task_type == SubTaskType.REFLECT and r.success and r.result:
                    new_output = r.result.get("output", "")
                    if new_output:
                        logger.info(
                            "AD-643b: Re-reflect updated output for %s",
                            self.agent_type,
                        )
                        return {
                            **original_result,
                            "llm_output": new_output,
                            "chain_source": f"{original_result.get('chain_source', '')}:re_reflect",
                        }

        except Exception as exc:
            logger.warning(
                "AD-643b: Re-reflect failed for %s, keeping original: %s",
                self.agent_type, exc,
            )

        return original_result

    async def act(self, decision: dict) -> dict:
        """Execute based on LLM decision.  Override for structured output."""
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}
        # AD-407b: pass through conversational responses for ward room
        if decision.get("intent") in ("direct_message", "ward_room_notification"):
            return {"success": True, "result": decision.get("llm_output", "")}
        return {
            "success": True,
            "result": decision.get("llm_output", ""),
        }

    async def report(self, result: dict) -> dict:
        """Package result as a dict (compatible with BaseAgent contract)."""
        return result

    async def _self_post_ward_room_response(
        self, intent: "IntentMessage", response_text: str,
    ) -> None:
        """AD-654a: Post own response to ward room after handling notification.

        When activated via JetStream dispatch (AD-654a), the agent is
        responsible for posting its own response — the router no longer
        collects IntentResults and posts on agents' behalf.
        """
        _rt = getattr(self, "_runtime", None)
        if not _rt or not getattr(_rt, "ward_room", None):
            return

        thread_id = intent.params.get("thread_id", "")
        if not thread_id:
            return

        # Use runtime-stored pipeline (created in _apply_finalization)
        pipeline = getattr(_rt, "ward_room_post_pipeline", None)
        if not pipeline:
            logger.debug("AD-654a: No ward_room_post_pipeline on runtime, skipping self-post")
            return

        try:
            await pipeline.process_and_post(
                agent=self,
                response_text=response_text,
                thread_id=thread_id,
                event_type=intent.params.get("event_type", ""),
                post_id=intent.params.get("post_id"),
            )
        except Exception:
            logger.warning(
                "AD-654a: Self-post failed for %s in thread %s",
                self.id[:12], thread_id[:12],
                exc_info=True,
            )

    async def _run_cognitive_lifecycle(
        self,
        intent: IntentMessage,
        cognitive_skill_instructions: str | None = None,
        skill_entries: list | None = None,
    ) -> IntentResult:
        """Execute the full cognitive lifecycle: perceive → decide → act → report.

        BF-239: Extracted from handle_intent so try/finally can wrap the
        call site without re-indenting ~370 lines. All existing returns
        (normal completion, compound procedure early return) are preserved.

        Args:
            intent: The IntentMessage being processed.
            cognitive_skill_instructions: AD-596b cognitive skill instructions (if any).
            skill_entries: AD-596b skill catalog entries matched for this intent (if any).
        """
        observation = await self.perceive(intent)

        # AD-430c (Pillar 4): Enrich observation with relevant episodic memories
        observation = await self._recall_relevant_memories(intent, observation)

        # AD-596b: Inject cognitive skill instructions into observation context
        if cognitive_skill_instructions:
            observation["cognitive_skill_instructions"] = cognitive_skill_instructions
            observation["cognitive_skill_name"] = skill_entries[0].name

        # AD-669: Inject sibling thread conclusions into observation
        _wm = getattr(self, '_working_memory', None)
        if _wm:
            _sibling_text = _wm.render_conclusions(exclude_thread=intent.id)
            if _sibling_text:
                observation["_sibling_conclusions"] = _sibling_text

        decision = await self.decide(observation)
        decision["intent"] = intent.intent  # AD-398: propagate intent name to act()
        # BF-177: propagate duty info so domain agents can distinguish duty-triggered thinks
        if observation.get("params", {}).get("duty"):
            decision["duty"] = observation["params"]["duty"]

        # AD-568e: Post-decision faithfulness verification
        _faithfulness = self._check_response_faithfulness(decision, observation)
        if _faithfulness is not None:
            observation["_faithfulness"] = _faithfulness
            if not _faithfulness.grounded:
                logger.info(
                    "AD-568e: Unfaithful response detected for %s (score=%.2f, overlap=%.2f, claims=%.2f)",
                    self.callsign or self.agent_type,
                    _faithfulness.score,
                    _faithfulness.evidence_overlap,
                    _faithfulness.unsupported_claim_ratio,
                )

        # AD-568e: Feed faithfulness signal to Counselor (fire-and-forget)
        if _faithfulness is not None:
            try:
                _rt = getattr(self, '_runtime', None)
                if _rt:
                    _counselors = _rt.registry.get_by_pool("counselor")
                    if _counselors:
                        _counselor = _counselors[0]
                        if hasattr(_counselor, 'record_faithfulness_event'):
                            await _counselor.record_faithfulness_event(
                                self.id,
                                faithfulness_score=_faithfulness.score,
                                grounded=_faithfulness.grounded,
                            )
            except Exception:
                logger.debug("AD-568e: Counselor faithfulness update failed", exc_info=True)

        # AD-589: Post-decision introspective faithfulness verification
        _intro_faith = self._check_introspective_faithfulness(decision)
        if _intro_faith is not None:
            observation["_introspective_faithfulness"] = _intro_faith
            if not _intro_faith.grounded:
                logger.info(
                    "AD-589: Introspective confabulation detected for %s (score=%.2f, claims=%d, contradictions=%d)",
                    self.callsign or self.agent_type,
                    _intro_faith.score,
                    _intro_faith.claims_detected,
                    len(_intro_faith.contradictions),
                )
                # AD-589: Emit SELF_MODEL_DRIFT event
                _rt = getattr(self, '_runtime', None)
                if _rt and hasattr(_rt, 'emit_event'):
                    try:
                        _rt.emit_event(EventType.SELF_MODEL_DRIFT, {
                            "agent_id": self.id,
                            "callsign": self.callsign or self.agent_type,
                            "score": _intro_faith.score,
                            "contradictions": _intro_faith.contradictions[:3],
                            "claims_detected": _intro_faith.claims_detected,
                            "correlation_id": observation.get("correlation_id", ""),
                        })
                    except Exception:
                        pass

        # AD-589: Feed introspective faithfulness to Counselor (fire-and-forget)
        if _intro_faith is not None:
            try:
                _rt = getattr(self, '_runtime', None)
                if _rt:
                    _counselors = _rt.registry.get_by_pool("counselor")
                    if _counselors:
                        _counselor = _counselors[0]
                        if hasattr(_counselor, 'record_faithfulness_event'):
                            await _counselor.record_faithfulness_event(
                                self.id,
                                faithfulness_score=_intro_faith.score,
                                grounded=_intro_faith.grounded,
                            )
            except Exception:
                logger.debug("AD-589: Counselor introspective update failed", exc_info=True)

        # AD-596c: Record cognitive skill exercise (fire-and-forget)
        if cognitive_skill_instructions and skill_entries:
            _bridge = getattr(self, '_skill_bridge', None)
            if _bridge:
                try:
                    import asyncio
                    asyncio.create_task(
                        _bridge.record_skill_exercise(self.id, skill_entries[0])
                    )
                except Exception:
                    logger.debug("AD-596c: Exercise recording task creation failed", exc_info=True)

        # AD-626: Record exercises for augmentation skills
        _aug_used = getattr(self, '_augmentation_skills_used', None)
        if _aug_used:
            _bridge = getattr(self, '_skill_bridge', None)
            if _bridge:
                for _aug_entry in _aug_used:
                    try:
                        import asyncio
                        asyncio.create_task(
                            _bridge.record_skill_exercise(self.id, _aug_entry)
                        )
                    except Exception:
                        logger.debug("AD-626: Aug skill exercise recording failed", exc_info=True)
            self._augmentation_skills_used = []

        # AD-534c: compound procedure dispatch
        if decision.get("compound") and decision.get("procedure"):
            compound_result = await self._execute_compound_replay(
                decision["procedure"], decision.get("llm_output", ""),
                compilation_level=decision.get("compilation_level", 4),
            )

            if compound_result.get("compound_dispatched"):
                # Record procedure completion (AD-534b metrics)
                _store = self._procedure_store
                if _store:
                    try:
                        await _store.record_completion(decision["procedure_id"])
                    except Exception:
                        pass

                # Emit task execution event (AD-532e)
                _rt = getattr(self, '_runtime', None)
                if _rt and hasattr(_rt, 'emit_event'):
                    try:
                        _rt.emit_event(EventType.TASK_EXECUTION_COMPLETE, {
                            "agent_id": self.id,
                            "agent_type": getattr(self, 'agent_type', ''),
                            "intent_type": intent.intent,
                            "success": True,
                            "used_procedure": True,
                            "compound_dispatched": True,
                            "steps_dispatched": compound_result.get("steps_dispatched", 0),
                            "correlation_id": observation.get("correlation_id", ""),
                        })
                    except Exception:
                        pass

                self.update_confidence(True)

                return IntentResult(
                    intent_id=intent.id,
                    agent_id=self.id,
                    success=True,
                    result=compound_result["result"],
                    confidence=self.confidence,
                )
            # Degradation: compound_dispatched=False — use text fallback in normal act() flow
            decision["llm_output"] = compound_result["result"]
            decision["compound"] = False  # prevent re-entry

        result = await self.act(decision)
        report = await self.report(result)

        # AD-573: Record action to working memory (all pathways)
        try:
            _wm = getattr(self, '_working_memory', None)
            if _wm:
                action_summary = self._summarize_action(intent, decision, result)
                if action_summary:
                    _wm.record_action(
                        action_summary,
                        source=intent.intent,
                    )
        except Exception:
            logger.debug("AD-573: Working memory action record failed", exc_info=True)

        # AD-669: Record conclusion for cross-thread sharing
        try:
            _wm = getattr(self, '_working_memory', None)
            if _wm:
                _conclusion_summary = self._extract_conclusion_summary(decision, result)
                if _conclusion_summary:
                    _conclusion_type = self._classify_conclusion(intent, decision)
                    _wm.record_conclusion(
                        thread_id=intent.id,
                        conclusion_type=_conclusion_type,
                        summary=_conclusion_summary,
                        relevance_tags=self._extract_relevance_tags(intent),
                        correlation_id=observation.get("correlation_id", ""),
                    )
                    _cycle_conclusions = [
                        conclusion for conclusion in _wm.get_active_conclusions()
                        if conclusion.thread_id == intent.id
                        and conclusion.correlation_id == observation.get("correlation_id", "")
                    ]
                    await self._store_important_conclusions_as_thoughts(
                        _cycle_conclusions,
                        correlation_id=observation.get("correlation_id", ""),
                    )
        except Exception:
            logger.debug("AD-669: Conclusion recording failed", exc_info=True)

        # AD-645 Phase 3: Store composition brief as metacognitive memory
        try:
            _wm = getattr(self, '_working_memory', None)
            if _wm and decision.get("sub_task_chain") and decision.get("_composition_brief"):
                brief = decision["_composition_brief"]
                if isinstance(brief, dict):
                    # Build a human-readable summary from the brief
                    _situation = brief.get("situation", "")
                    _cover = brief.get("response_should_cover")
                    if isinstance(_cover, list):
                        _cover_text = "; ".join(str(c) for c in _cover[:3])
                    else:
                        _cover_text = str(_cover) if _cover else ""
                    summary_parts = []
                    if _situation:
                        summary_parts.append(_situation)
                    if _cover_text:
                        summary_parts.append(f"Planned to cover: {_cover_text}")
                    if summary_parts:
                        _wm.record_reasoning(
                            " | ".join(summary_parts),
                            source=intent.intent,
                            metadata={"composition_brief": brief},
                            knowledge_source="reasoning",
                        )
        except Exception:
            logger.debug("AD-645: Composition brief storage failed", exc_info=True)

        # AD-430c (Pillar 5): Store action as episodic memory for crew agents
        # AD-632g: Propagate chain metadata into observation for episode storage
        if decision.get("sub_task_chain"):
            observation["_chain_metadata"] = {
                "sub_task_chain": True,
                "chain_source": decision.get("chain_source", ""),
                "chain_steps": decision.get("chain_steps", 0),
            }
        await self._store_action_episode(intent, observation, report)

        success = report.get("success", False)

        # AD-534b: Post-execution metric recording for procedure replay
        if decision.get("cached") and decision.get("procedure_id"):
            _store = self._procedure_store
            if _store:
                try:
                    if success:
                        await _store.record_completion(decision["procedure_id"])
                    else:
                        await _store.record_fallback(decision["procedure_id"])
                except Exception:
                    pass  # Never block intent pipeline for metrics

        # AD-535: Track Level 2 (Guided) procedure association
        if decision.get("guided_by_procedure") and decision.get("procedure_id"):
            _store = self._procedure_store
            if _store:
                try:
                    if success:
                        await _store.record_completion(decision["procedure_id"])
                    else:
                        await _store.record_fallback(decision["procedure_id"])
                except Exception:
                    pass

        # AD-535: Compilation level promotion/demotion
        _proc_id_for_promo = decision.get("procedure_id")
        if _proc_id_for_promo and self._procedure_store:
            _store = self._procedure_store
            if success:
                try:
                    new_count = await _store.record_consecutive_success(_proc_id_for_promo)
                    from probos.config import (
                        COMPILATION_PROMOTION_THRESHOLD,
                        COMPILATION_MAX_LEVEL,
                    )
                    proc = await _store.get(_proc_id_for_promo)
                    if proc and new_count >= COMPILATION_PROMOTION_THRESHOLD:
                        _ts = getattr(self, "_trust_score", 0.5)
                        # AD-536: Check if promoted procedure can reach Level 5
                        _promo_status = await _store.get_promotion_status(_proc_id_for_promo)
                        max_allowed = self._max_compilation_level_for_promoted(_ts, _promo_status)
                        next_level = proc.compilation_level + 1
                        if next_level <= min(max_allowed, COMPILATION_MAX_LEVEL):
                            await _store.promote_compilation_level(_proc_id_for_promo, next_level)
                            logger.info(
                                "Procedure '%s' promoted to Level %d after %d consecutive successes",
                                proc.name, next_level, new_count,
                            )
                            # AD-536: Check if procedure is eligible for institutional promotion
                            from probos.config import PROMOTION_MIN_COMPILATION_LEVEL
                            promo_status = await _store.get_promotion_status(_proc_id_for_promo)
                            if next_level >= PROMOTION_MIN_COMPILATION_LEVEL and promo_status == "private":
                                await self._request_procedure_promotion(_proc_id_for_promo)
                except Exception:
                    pass
            else:
                try:
                    from probos.config import COMPILATION_DEMOTION_LEVEL
                    proc = await _store.get(_proc_id_for_promo)
                    if proc and proc.compilation_level > COMPILATION_DEMOTION_LEVEL:
                        await _store.demote_compilation_level(
                            _proc_id_for_promo, COMPILATION_DEMOTION_LEVEL
                        )
                        logger.info(
                            "Procedure '%s' demoted to Level %d after failure",
                            proc.name, COMPILATION_DEMOTION_LEVEL,
                        )
                    else:
                        await _store.reset_consecutive_successes(_proc_id_for_promo)
                except Exception:
                    pass

        # AD-534b: Service recovery — re-run LLM on cached execution failure
        llm_decision = None
        if decision.get("cached") and not success:
            _proc_name = decision.get("procedure_name", "")
            _proc_id = decision.get("procedure_id", "")
            logger.debug("Procedure replay failed, attempting LLM fallback: procedure=%s", _proc_name)
            try:
                llm_decision = await self._run_llm_fallback(observation)
                if llm_decision is not None:
                    llm_result = await self.act(llm_decision)
                    llm_report = await self.report(llm_result)
                    llm_success = llm_report.get("success", False)
                    if llm_success:
                        # Service recovery succeeded — use LLM result
                        result = llm_result
                        report = llm_report
                        success = True
                        # Capture fallback learning event
                        self._last_fallback_info = {
                            "type": "execution_failure",
                            "procedure_id": _proc_id,
                            "procedure_name": _proc_name,
                            "reason": "Procedure replay succeeded in formatting but failed in execution",
                        }
            except Exception:
                logger.debug("LLM fallback recovery failed", exc_info=True)
                # Original failure stands — user sees the procedure's error

        self.update_confidence(success)

        # AD-532e: Reactive trigger — emit task completion for procedure evolution monitoring
        _rt = getattr(self, '_runtime', None)
        if _rt and hasattr(_rt, 'emit_event'):
            try:
                _rt.emit_event(EventType.TASK_EXECUTION_COMPLETE, {
                    "agent_id": self.id,
                    "agent_type": getattr(self, 'agent_type', ''),
                    "intent_type": intent.intent,
                    "success": success,
                    "used_procedure": decision.get("cached", False),
                    "correlation_id": observation.get("correlation_id", ""),
                })
            except Exception:
                pass  # Fire-and-forget, never block the intent pipeline

        # AD-534b: Emit fallback learning event for dream-time processing
        if success and self._last_fallback_info is not None:
            if _rt and hasattr(_rt, 'emit_event'):
                try:
                    from probos.config import MAX_FALLBACK_RESPONSE_CHARS
                    _llm_output = ""
                    if llm_decision is not None:
                        _llm_output = llm_decision.get("llm_output", "")
                    else:
                        _llm_output = decision.get("llm_output", "")
                    _rt.emit_event(EventType.PROCEDURE_FALLBACK_LEARNING, {
                        "agent_id": self.id,
                        "intent_type": intent.intent,
                        "fallback_type": self._last_fallback_info["type"],
                        "procedure_id": self._last_fallback_info["procedure_id"],
                        "procedure_name": self._last_fallback_info.get("procedure_name", ""),
                        "near_miss_score": self._last_fallback_info.get("score", 0.0),
                        "rejection_reason": self._last_fallback_info.get("reason", ""),
                        "llm_response": _llm_output[:MAX_FALLBACK_RESPONSE_CHARS],
                        "timestamp": time.time(),
                        "correlation_id": observation.get("correlation_id", ""),
                    })
                except Exception:
                    pass  # Fire-and-forget
            self._last_fallback_info = None  # Consumed

        # AD-654a: Agent self-posting for ward_room_notification
        if intent.intent == "ward_room_notification" and success and report.get("result"):
            await self._self_post_ward_room_response(intent, str(report["result"]))

        # AD-492: Clear correlation_id — cycle complete
        _wm = getattr(self, '_working_memory', None)
        if _wm:
            _wm.clear_correlation_id()
        self._current_correlation_id = ""

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("result"),
            error=report.get("error"),
            confidence=self.confidence,
        )

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Skills first, then cognitive lifecycle.

        Returns None (self-deselect) for intents not in _handled_intents,
        unless it's a targeted direct_message (AD-397 1:1 sessions).
        """
        # AD-397: always accept direct_message if targeted to this agent
        # AD-407b: always accept ward_room_notification if targeted to this agent
        is_direct = (
            intent.intent in ("direct_message", "ward_room_notification", "proactive_think", "compound_step_replay")
            and intent.target_agent_id == self.id
        )

        # BF-239: Ward Room thread engagement gate — skip if already
        # replied to this thread in the current round. Uses working memory
        # engagement tracking (serial queue guarantees no race).
        # @mentions and DMs bypass — same principle as BF-236/cooldown gates.
        _bf239_thread_id = ""
        if intent.intent == "ward_room_notification":
            _bf239_thread_id = intent.params.get("thread_id", "")
            _bf239_mentioned = intent.params.get("was_mentioned", False)
            _bf239_is_dm = intent.params.get("is_dm_channel", False)
            if _bf239_thread_id and not _bf239_mentioned and not _bf239_is_dm:
                _wm = getattr(self, '_working_memory', None)
                if _wm and _wm.has_thread_engagement(_bf239_thread_id):
                    logger.debug(
                        "BF-239: %s already engaged with thread %s, skipping",
                        getattr(self, 'callsign', '') or self.agent_type,
                        _bf239_thread_id[:8],
                    )
                    # [NO_RESPONSE] with current confidence — the agent handled
                    # the intent (chose silence), it did not fail. No
                    # update_confidence() call: no cognitive work was performed,
                    # so Trust/Hebbian feedback should not see this event.
                    return IntentResult(
                        intent_id=intent.id,
                        agent_id=self.id,
                        success=True,
                        result="[NO_RESPONSE]",
                        confidence=self.confidence,
                    )

        # Fast path: self-deselect for unrecognized intents before any LLM call
        # AD-596b: Check cognitive skill catalog before self-deselecting
        _cognitive_skill_instructions = None
        _skill_entries = None  # BF-239: must be defined for _run_cognitive_lifecycle call
        if not is_direct and intent.intent not in self._handled_intents:
            _catalog = getattr(self, '_cognitive_skill_catalog', None)
            if _catalog:
                _skill_entries = _catalog.find_by_intent(intent.intent)
                if _skill_entries:
                    _entry = _skill_entries[0]
                    # AD-596c: Proficiency gate — check before loading instructions
                    _bridge = getattr(self, '_skill_bridge', None)
                    if _bridge:
                        _profile = getattr(self, '_skill_profile', None)
                        if not _bridge.check_proficiency_gate(self.id, _entry, _profile):
                            return None  # Silent self-deselect — agent lacks proficiency
                    _cognitive_skill_instructions = _catalog.get_instructions(_entry.name)
                    if _cognitive_skill_instructions:
                        logger.info(
                            "AD-596b: Loaded cognitive skill '%s' for intent '%s' on %s",
                            _entry.name, intent.intent, self.agent_type,
                        )
                    else:
                        return None
                else:
                    return None
            else:
                return None

        # AD-534c: compound step replay — zero-token, bypass full cognitive lifecycle
        if intent.intent == "compound_step_replay" and intent.target_agent_id == self.id:
            return await self._handle_compound_step_replay(intent)

        # Skill dispatch — direct handler call, no LLM reasoning
        if intent.intent in self._skills:
            skill = self._skills[intent.intent]
            return await skill.handler(intent, llm_client=self._llm_client)

        # BF-239: Register ward room thread engagement before cognitive lifecycle.
        # Recorded here (after skill dispatch, before lifecycle) so that:
        # 1. The engagement exists before any await (perceive's LLM call)
        # 2. Skill-dispatched intents don't get engagement-tracked
        # Key namespaced as "ward_room:{thread_id}" to avoid collision
        # with game engagements that use raw game_id as engagement_id.
        if _bf239_thread_id:
            # Function-local import: cognitive_agent.py does not import
            # ActiveEngagement at module level (only AgentWorkingMemory,
            # and that's also function-local at line 100). Keeping the
            # pattern consistent avoids circular import risk.
            from probos.cognitive.agent_working_memory import ActiveEngagement
            _wm = getattr(self, '_working_memory', None)
            if _wm:
                _wm.add_engagement(ActiveEngagement(
                    engagement_type="ward_room_reply",
                    engagement_id=f"ward_room:{_bf239_thread_id}",
                    summary=f"Replying to Ward Room thread {_bf239_thread_id[:8]}",
                    state={"thread_id": _bf239_thread_id},
                ))

        concurrency_manager = getattr(self, "_concurrency_manager", None)
        if concurrency_manager:
            priority = _classify_concurrency_priority(intent)
            try:
                async with concurrency_manager.slot(intent.intent, priority):
                    return await self._run_cognitive_lifecycle(
                        intent, _cognitive_skill_instructions, _skill_entries,
                    )
            except ValueError:
                logger.warning(
                    "AD-672: Concurrency queue full for %s on intent '%s'; "
                    "returning [NO_RESPONSE] to shed load",
                    getattr(self, 'callsign', '') or self.agent_type,
                    intent.intent,
                )
                return IntentResult(
                    intent_id=intent.id,
                    agent_id=self.id,
                    success=True,
                    result="[NO_RESPONSE]",
                    confidence=self.confidence,
                )
            finally:
                if _bf239_thread_id:
                    _wm = getattr(self, '_working_memory', None)
                    if _wm:
                        _wm.remove_engagement(f"ward_room:{_bf239_thread_id}")

        try:
            return await self._run_cognitive_lifecycle(
                intent, _cognitive_skill_instructions, _skill_entries,
            )
        finally:
            # BF-239: Remove ward room thread engagement on ALL exit paths.
            # Covers: normal completion, compound procedure early return,
            # and exceptions from perceive/decide/act/report.
            # The engagement is the short-lived "I'm currently working on this" signal.
            # Historical record preserved via _summarize_action (Section 5).
            if _bf239_thread_id:
                _wm = getattr(self, '_working_memory', None)
                if _wm:
                    _wm.remove_engagement(f"ward_room:{_bf239_thread_id}")

    def add_skill(self, skill: Skill) -> None:
        """Attach a skill to this cognitive agent.

        Updates BOTH instance-level AND class-level _handled_intents
        and intent_descriptors so that both the agent's own dispatch
        and the template-based descriptor collection path work.
        """
        self._skills[skill.descriptor.name] = skill

        # Instance-level update (for this agent's dispatch)
        self._handled_intents.add(skill.descriptor.name)
        if skill.descriptor not in self.intent_descriptors:
            self.intent_descriptors.append(skill.descriptor)

        # Class-level update (for template-based descriptor collection in
        # _collect_intent_descriptors, which reads class.intent_descriptors)
        cls = type(self)
        if skill.descriptor not in cls.intent_descriptors:
            cls.intent_descriptors = [*cls.intent_descriptors, skill.descriptor]
        cls._handled_intents = cls._handled_intents | {skill.descriptor.name}

    def remove_skill(self, intent_name: str) -> None:
        """Remove a skill from this cognitive agent.

        Updates both instance and class level.
        """
        if intent_name not in self._skills:
            return
        self._skills.pop(intent_name)
        self._handled_intents.discard(intent_name)
        self.intent_descriptors = [
            d for d in self.intent_descriptors if d.name != intent_name
        ]
        # Class-level cleanup
        cls = type(self)
        cls._handled_intents = cls._handled_intents - {intent_name}
        cls.intent_descriptors = [
            d for d in cls.intent_descriptors if d.name != intent_name
        ]

    def _resolve_callsign(self) -> str | None:
        """Resolve current callsign with identity registry fallback (BF-101)."""
        if self.callsign:
            return self.callsign
        # Fallback: check birth certificate
        rt = getattr(self, '_runtime', None)
        if rt and hasattr(rt, '_identity_registry') and rt._identity_registry:
            cert = rt._identity_registry.get_by_slot(self.id)
            if cert and cert.callsign:
                # Restore to live attribute for future calls
                self.callsign = cert.callsign
                logger.warning("BF-101: Restored callsign '%s' from birth cert for %s",
                             cert.callsign, self.agent_type)
                return cert.callsign
        return None

    def _get_comm_proficiency_guidance(self) -> str | None:
        """AD-625: Return tier-specific communication guidance based on proficiency."""
        profile = getattr(self, '_skill_profile', None)
        if not profile:
            return None
        for rec in profile.all_skills:
            if rec.skill_id == "communication":
                from probos.cognitive.comm_proficiency import get_prompt_guidance
                return get_prompt_guidance(rec.proficiency)
        return None

    def _load_augmentation_skills(self, intent: str) -> str:
        """AD-626: Load augmentation skill instructions for a handled intent.

        Returns concatenated skill guidance sections, or empty string.
        Augmentation skills enhance existing behavior — they don't provide
        new capabilities. Think: cognitive tools that extend natural ability.
        """
        if not intent:
            return ""
        catalog = getattr(self, '_cognitive_skill_catalog', None)
        if not catalog:
            if _SKILL_DEBUG:
                logger.info("AD-626 [SKILL_DEBUG]: No catalog on %s", self.agent_type)
            return ""

        department = getattr(self, 'department', None)
        rank = getattr(self, 'rank', None)
        rank_val = rank.value if hasattr(rank, 'value') else rank

        entries = catalog.find_augmentation_skills(
            intent, department=department, agent_rank=rank_val,
        )
        if not entries:
            if _SKILL_DEBUG:
                logger.info(
                    "AD-626 [SKILL_DEBUG]: No augmentation skills matched intent='%s' "
                    "dept='%s' rank='%s' on %s (catalog has %d skills)",
                    intent, department, rank_val, self.agent_type,
                    len(catalog._cache),
                )
            self._augmentation_skills_used = []
            return ""

        bridge = getattr(self, '_skill_bridge', None)
        profile = getattr(self, '_skill_profile', None)
        parts = []
        loaded_entries = []
        for entry in entries:
            if bridge and not bridge.check_proficiency_gate(self.id, entry, profile):
                if _SKILL_DEBUG:
                    logger.info(
                        "AD-626 [SKILL_DEBUG]: Proficiency gate blocked '%s' on %s",
                        entry.name, self.agent_type,
                    )
                continue
            instructions = catalog.get_instructions(entry.name)
            if instructions:
                parts.append(instructions)
                loaded_entries.append(entry)
                logger.info(
                    "AD-626: Loaded augmentation skill '%s' for intent '%s' on %s",
                    entry.name, intent, self.agent_type,
                )

        self._augmentation_skills_used = loaded_entries
        return "".join(parts)

    def _frame_task_with_skill(
        self,
        skill_instructions: str,
        task_label: str,
        context_summary: str = "",
        proficiency_context: str = "",
    ) -> list[str]:
        """AD-626/AD-631: Generic task-framed skill injection with XML tags.

        Produces preamble lines that frame a task with augmentation skill
        instructions. The caller appends task-specific content after these
        lines. This is the single injection mechanism for all intent types —
        skill content and framing are task-type-agnostic. Specific metadata
        (e.g. thread reply counts) is provided by the caller via
        context_summary.
        """
        # Derive skill name from loaded augmentation skills
        _skill_name = task_label.lower().replace(" ", "-")
        if self._augmentation_skills_used:
            _skill_name = self._augmentation_skills_used[0].name

        lines = [""]
        lines.append(f'<active_skill name="{_skill_name}" activation="augmentation">')
        if proficiency_context:
            lines.append(f"<proficiency_tier>{proficiency_context}</proficiency_tier>")
        if context_summary:
            lines.append(f"<skill_context>{context_summary}</skill_context>")
        lines.append("<skill_instructions>")
        lines.append(
            "Follow these instructions internally when processing the "
            "content below. Your response must contain ONLY your final "
            "output — no reasoning steps, phase headers, or self-evaluation "
            "artifacts."
        )
        lines.append("")
        lines.append(skill_instructions)
        lines.append("</skill_instructions>")
        lines.append("</active_skill>")
        lines.append("")
        return lines

    @staticmethod
    def _extract_thread_metadata(thread_text: str) -> str:
        """Extract reply count and contributor callsigns from Ward Room thread text.

        Returns a summary string like 'Replies so far: ~3 | Contributors: A, B'
        or empty string if no metadata can be extracted. This is Ward-Room-
        specific context passed to the generic _frame_task_with_skill().
        """
        if not thread_text:
            return ""
        _lines = thread_text.strip().split("\n")
        _reply_count = sum(
            1 for ln in _lines
            if ln.strip().startswith("- ") or ln.strip().startswith("Reply from")
        )
        _callsigns: set[str] = set()
        for ln in _lines:
            for marker in ("posted:", "Reply from ", "— "):
                idx = ln.find(marker)
                if idx != -1:
                    _cs = ln[idx + len(marker):].strip().split()[0].rstrip(":,")
                    if _cs and len(_cs) < 30:
                        _callsigns.add(_cs)
        _parts: list[str] = []
        if _reply_count > 0:
            _parts.append(f"Replies so far: ~{_reply_count}")
        if _callsigns:
            _parts.append(f"Contributors: {', '.join(sorted(_callsigns))}")
        return " | ".join(_parts) if _parts else ""

    def _detect_self_in_content(self, content: str) -> str:
        """Detect if agent's own callsign appears in content and return grounding cue.

        AD-575: Cross-context self-recognition. When the agent's callsign
        appears in Ward Room thread content, return a grounding note so the
        agent recognizes itself as a participant, not an observer.

        Returns a grounding string, or empty string if no self-mention detected.
        """
        callsign = self._resolve_callsign()
        if not callsign:
            return ""

        if not re.search(rf"\b{re.escape(callsign)}\b", content, re.IGNORECASE):
            return ""

        # Self-mention detected — build grounding cue
        cue_parts: list[str] = [
            f"IMPORTANT: Your callsign is {callsign}. References to"
            f" '{callsign}' in the thread above refer to YOU."
            f" You are a participant in what is being discussed, not an"
            f" outside observer. Respond from your perspective as a participant.",
        ]

        # Cross-context engagement binding (AD-572/573)
        _wm = getattr(self, "_working_memory", None)
        if _wm and _wm.has_engagement("game"):
            games = _wm.get_engagements_by_type("game")
            if games:
                g = games[0]
                game_type = g.state.get("game_type", "game")
                opponent = g.state.get("opponent", "")
                cue_parts.append(
                    f"You have an active {game_type} game"
                    + (f" against {opponent}" if opponent else "")
                    + ". Spectators are watching your game in this thread."
                    + " Engage from your perspective as the player."
                )

        return "\n".join(cue_parts)

    def _has_active_game(self) -> bool:
        """AD-572: Check if this agent has an active game (lightweight check)."""
        rt = getattr(self, '_runtime', None)
        if not rt:
            return False
        rec_svc = getattr(rt, 'recreation_service', None)
        if not rec_svc:
            return False
        callsign = self._resolve_callsign()
        if not callsign:
            return False
        try:
            return rec_svc.get_game_by_player(callsign) is not None
        except Exception:
            return False

    def _build_active_game_context(self) -> str | None:
        """AD-572: Build active game context for DM awareness.

        Returns a formatted string if this agent has an active game, else None.
        Uses RecreationService.get_game_by_player() (AD-572 DRY method).
        """
        rt = getattr(self, '_runtime', None)
        if not rt:
            return None
        rec_svc = getattr(rt, 'recreation_service', None)
        if not rec_svc:
            return None

        callsign = self._resolve_callsign()
        if not callsign:
            return None

        try:
            game = rec_svc.get_game_by_player(callsign)
            if not game:
                return None

            game_id = game["game_id"]
            state = game.get("state", {})
            opponent = next(
                (p for p in [game.get("challenger", ""), game.get("opponent", "")]
                 if p != callsign),
                "unknown",
            )
            board = rec_svc.render_board(game_id)
            is_my_turn = state.get("current_player") == callsign
            valid_moves = rec_svc.get_valid_moves(game_id) if is_my_turn else []

            lines = ["--- Active Game ---"]
            lines.append(
                f"You are playing {game.get('game_type', 'a game')} against {opponent}. "
                f"Moves so far: {game.get('moves_count', 0)}."
            )
            lines.append(f"\nCurrent board:\n```\n{board}\n```")
            if is_my_turn:
                lines.append(
                    f"**It is YOUR turn.** Valid moves: {', '.join(str(m) for m in valid_moves)}. "
                    f"Reply with [MOVE position] to play."
                )
            else:
                lines.append("Waiting for your opponent to move.")
            return "\n".join(lines)
        except Exception:
            return None

    def _summarize_action(self, intent, decision: dict, result: dict) -> str:
        """AD-573: Produce a one-line summary of what I just did."""
        intent_type = intent.intent
        output = (decision.get("llm_output") or "")[:200]

        if intent_type == "direct_message":
            captain_text = intent.params.get("text", "")[:100]
            return f"Responded to Captain's DM: '{captain_text}' → '{output[:100]}'"
        if intent_type == "ward_room_notification":
            channel = intent.params.get("channel_name", "")
            thread_id = intent.params.get("thread_id", "")
            _thread_tag = f" (thread {thread_id[:8]})" if thread_id else ""
            return f"Responded in Ward Room #{channel}{_thread_tag}: '{output[:100]}'"
        if intent_type == "proactive_think":
            if "[NO_RESPONSE]" in output:
                return ""  # Don't record silence
            return f"Proactive observation: '{output[:150]}'"
        return f"Handled {intent_type}: '{output[:100]}'"

    @staticmethod
    def _extract_conclusion_summary(decision: dict, result: dict) -> str:
        """AD-669: Extract a one-line conclusion from chain execution results."""
        llm_output = decision.get("llm_output", "")
        if not llm_output or "[NO_RESPONSE]" in llm_output:
            return ""

        brief = decision.get("_composition_brief")
        if isinstance(brief, dict):
            situation = brief.get("situation", "")
            if situation:
                return situation[:200]

        first_line = llm_output.split("\n")[0].strip()
        if len(first_line) > 200:
            return first_line[:197] + "..."
        return first_line

    @staticmethod
    def _classify_conclusion(intent, decision: dict) -> "ConclusionType":
        """AD-669: Classify conclusion type from intent and decision context."""
        from probos.cognitive.agent_working_memory import ConclusionType

        llm_output = (decision.get("llm_output") or "").lower()
        if "escalat" in llm_output or "captain" in llm_output or decision.get("compound"):
            return ConclusionType.ESCALATION
        if intent.intent == "proactive_think":
            return ConclusionType.OBSERVATION
        if decision.get("duty"):
            return ConclusionType.COMPLETION
        return ConclusionType.DECISION

    @staticmethod
    def _map_conclusion_to_thought_type(conclusion: Any) -> str:
        """AD-606: Map a ConclusionEntry type to a thought type string."""
        conclusion_type = conclusion.conclusion_type
        conclusion_value = conclusion_type.value if hasattr(conclusion_type, "value") else str(conclusion_type)
        mapping = {
            "decision": "conclusion",
            "observation": "observation_synthesis",
            "escalation": "conclusion",
            "completion": "conclusion",
        }
        return mapping.get(conclusion_value, "conclusion")

    async def _store_important_conclusions_as_thoughts(
        self,
        conclusions: list[Any],
        *,
        correlation_id: str = "",
    ) -> None:
        """AD-606: Persist important working-memory conclusions as thought episodes."""
        if self._thought_store is None:
            if not self._runtime:
                return
            try:
                _ts_config = self._runtime.config.thought_store
                if not _ts_config.enabled:
                    return
                from probos.cognitive.thought_store import ThoughtStore

                self._thought_store = ThoughtStore(
                    episodic_memory=self._runtime.episodic_memory,
                    config=_ts_config,
                    identity_registry=getattr(self._runtime, "identity_registry", None),
                )
            except Exception:
                logger.debug("AD-606: ThoughtStore unavailable", exc_info=True)
                return

        if not conclusions:
            return

        try:
            active_correlation_id = correlation_id or self._current_correlation_id
            self._thought_store.reset_cycle(active_correlation_id)
            for conclusion in conclusions[:3]:
                await self._thought_store.store_thought(
                    agent_id=self.id,
                    thought=conclusion.summary,
                    thought_type=self._map_conclusion_to_thought_type(conclusion),
                    importance=6,
                    correlation_id=active_correlation_id,
                )
        except Exception:
            logger.debug("AD-606: Thought storage failed; continuing without thought memory", exc_info=True)

    @staticmethod
    def _extract_relevance_tags(intent) -> list[str]:
        """AD-669: Extract relevance tags from the intent for conclusion indexing."""
        tags: list[str] = []
        if intent.intent:
            tags.append(intent.intent)
        channel = intent.params.get("channel_name", "")
        if channel:
            tags.append(f"channel:{channel}")
        topic = intent.params.get("topic", "")
        if topic:
            tags.append(f"topic:{topic}")
        return tags[:5]

    async def _build_dm_self_monitoring(self, thread_id: str) -> str | None:
        """AD-623: Lightweight self-monitoring for DM/WR response path.

        Check this agent's own recent posts in the thread for self-repetition.
        Returns a warning string if similarity is high, None otherwise.
        """
        rt = getattr(self, '_runtime', None)
        if not rt or not hasattr(rt, 'ward_room') or not rt.ward_room:
            return None

        try:
            callsign = getattr(self, 'callsign', None) or getattr(self, 'agent_type', '')
            posts = await rt.ward_room.get_posts_by_author(
                callsign, limit=3, thread_id=thread_id,
            )
            if not posts or len(posts) < 2:
                return None

            from probos.cognitive.similarity import jaccard_similarity, text_to_words
            word_sets = [text_to_words(p["body"]) for p in posts]
            total_sim = 0.0
            pair_count = 0
            for j in range(len(word_sets)):
                for k in range(j + 1, len(word_sets)):
                    total_sim += jaccard_similarity(word_sets[j], word_sets[k])
                    pair_count += 1

            if pair_count > 0:
                avg_sim = total_sim / pair_count
                if avg_sim >= 0.4:
                    return (
                        "--- Self-monitoring (AD-623) ---\n"
                        f"WARNING: Your last {len(posts)} messages in this thread "
                        f"show {avg_sim:.0%} self-similarity. You may be repeating "
                        "yourself. If you and the other person agree, conclude the "
                        "conversation naturally. Do NOT restate conclusions you've "
                        "already communicated. If there's nothing new to add, "
                        "respond with exactly: [NO_RESPONSE]"
                    )
        except Exception:
            logger.debug("AD-623: DM self-monitoring failed", exc_info=True)

        return None

    async def handle_consultation_request(self, request: Any) -> Any:
        """AD-594: Handle an incoming expert consultation request."""
        from probos.cognitive.consultation import ConsultationResponse

        callsign = getattr(self, "callsign", None) or self.agent_type
        logger.info(
            "AD-594: %s handling consultation on '%s' from %s",
            callsign,
            request.topic,
            request.requester_callsign or request.requester_id,
        )

        system_prompt = (
            f"You are {callsign}, responding to an expert consultation.\n"
            f"Topic: {request.topic}\n"
            f"Question: {request.question}\n"
        )
        if request.required_expertise:
            system_prompt += f"Required expertise: {request.required_expertise}\n"
        if request.context:
            system_prompt += f"Additional context: {request.context}\n"

        system_prompt += (
            "\nProvide a concise, expert answer. Include your reasoning summary. "
            "Rate your confidence (0.0-1.0) in your answer. "
            "If you are not confident, say so honestly."
        )

        user_message = request.question or request.topic
        answer = ""
        confidence = 0.5
        reasoning = ""

        runtime = getattr(self, "_runtime", None)
        llm = getattr(self, "_llm_client", None) or (
            getattr(runtime, "llm_client", None) if runtime else None
        )
        if llm:
            try:
                from probos.types import LLMRequest
                llm_request = LLMRequest(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    tier="fast",
                )
                llm_response = await llm.complete(llm_request)
                answer = (
                    llm_response.content
                    if hasattr(llm_response, "content")
                    else str(llm_response)
                )
                confidence = 0.6
                reasoning = f"Consulted on {request.topic}"
            except Exception:
                logger.warning(
                    "AD-594: LLM call failed for consultation by %s; providing fallback",
                    callsign,
                    exc_info=True,
                )
                answer = f"I did not complete a full analysis of '{request.topic}' at this time."
                confidence = 0.2
                reasoning = "LLM call failed; low-confidence fallback response"
        else:
            answer = (
                f"Acknowledged consultation on '{request.topic}'; "
                "no LLM client is available for detailed analysis."
            )
            confidence = 0.1
            reasoning = "No LLM client available"

        return ConsultationResponse(
            request_id=request.request_id,
            responder_id=self.id,
            responder_callsign=callsign,
            answer=answer,
            confidence=confidence,
            reasoning_summary=reasoning,
        )

    def _build_temporal_context(self) -> str:
        """AD-502: Build temporal awareness header for agent prompts."""
        # Respect config if available
        rt = getattr(self, '_runtime', None)
        if rt and hasattr(rt, 'config') and hasattr(rt.config, 'temporal'):
            if not rt.config.temporal.enabled:
                return ""
            tcfg = rt.config.temporal
        else:
            tcfg = None  # No config available — include everything

        now = datetime.now(timezone.utc)
        parts = [f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')} ({now.strftime('%A')})"]

        # Birth age
        if (tcfg is None or tcfg.include_birth_time):
            birth_ts = getattr(self, '_birth_timestamp', None)
            if birth_ts:
                birth_dt = datetime.fromtimestamp(birth_ts, tz=timezone.utc)
                age = (now - birth_dt).total_seconds()
                parts.append(f"Your birth: {birth_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} (age: {format_duration(age)})")
                # BF-102: Commissioning awareness for newly arrived crew
                if age < 300:
                    parts.append(
                        f"You were commissioned {format_duration(age)} ago. "
                        "You are a newly arrived crew member. "
                        "If someone welcomes you or mentions your name, "
                        "they are talking about YOU — respond as yourself."
                    )

        # System uptime
        if (tcfg is None or tcfg.include_system_uptime):
            sys_start = getattr(self, '_system_start_time', None)
            if sys_start:
                uptime = time.time() - sys_start
                parts.append(f"System uptime: {format_duration(uptime)}")

        # Last action recency
        if (tcfg is None or tcfg.include_last_action):
            if hasattr(self, 'meta') and self.meta.last_active:
                since_last = (now - self.meta.last_active).total_seconds()
                parts.append(f"Your last action: {format_duration(since_last)} ago")

        # Post count
        if (tcfg is None or tcfg.include_post_count):
            post_count = getattr(self, '_recent_post_count', None)
            if post_count is not None:
                parts.append(f"Your posts this hour: {post_count}")

        # AD-567g: Cognitive re-localization orientation
        orientation = getattr(self, '_orientation_rendered', None)
        if orientation:
            parts.append(orientation)

        # AD-513: Crew complement grounding (anti-confabulation)
        crew_complement = self._build_crew_complement()
        if crew_complement:
            parts.append(crew_complement)

        return "\n".join(parts)

    def _build_cognitive_baseline(self, observation: dict) -> dict[str, str]:
        """AD-646: Agent-intrinsic cognitive state — runs for ALL chain executions.

        Produces baseline self-knowledge from agent attributes and runtime
        services. Zero dependency on context_parts (which only proactive.py
        populates). Ward Room chains get temporal awareness, working memory,
        trust metrics, ontology, and confabulation guards.
        """
        state: dict[str, str] = {}

        # 1. Temporal awareness (AD-502) — self-contained
        temporal = self._build_temporal_context()
        if temporal:
            state["_temporal_context"] = temporal

        # 2. Working memory (AD-573) — self-contained
        _wm = getattr(self, '_working_memory', None)
        if _wm:
            wm_text = _wm.render_context(budget=1500)
            if wm_text:
                state["_working_memory_context"] = wm_text

        # 3. Agent metrics — computed from runtime (not _params)
        try:
            _rt = getattr(self, '_runtime', None)
            _trust_val = 0.5
            _rank_val = "ensign"
            _agency_val = "ensign"
            if _rt and hasattr(_rt, 'trust_network'):
                from probos.crew_profile import Rank
                from probos.earned_agency import agency_from_rank
                from probos.config import format_trust
                _trust_val = _rt.trust_network.get_score(self.id)
                _rank_val = Rank.from_trust(_trust_val).value
                _agency_val = agency_from_rank(Rank.from_trust(_trust_val)).value
                _trust_val = format_trust(_trust_val)
            state["_agent_metrics"] = (
                f"Your trust: {_trust_val} | "
                f"Agency: {_agency_val} | "
                f"Rank: {_rank_val}"
            )
        except Exception:
            logger.debug("AD-646: Agent metrics baseline computation failed", exc_info=True)
            state["_agent_metrics"] = "Your trust: 0.5 | Agency: ensign | Rank: ensign"

        # 4. Ontology identity grounding — computed from runtime
        try:
            _rt = getattr(self, '_runtime', None)
            if _rt and hasattr(_rt, 'ontology'):
                ontology = _rt.ontology.get_crew_context(self.agent_type)
                if ontology:
                    onto_parts: list[str] = []
                    identity = ontology.get("identity", {})
                    dept = ontology.get("department", {})
                    vessel = ontology.get("vessel", {})
                    onto_parts.append(
                        f"You are {identity.get('callsign', '?')}, "
                        f"{identity.get('post', '?')} in {dept.get('name', '?')} department."
                    )
                    if ontology.get("reports_to"):
                        onto_parts.append(f"You report to {ontology['reports_to']}.")
                    if ontology.get("direct_reports"):
                        onto_parts.append(f"Your direct reports: {', '.join(ontology['direct_reports'])}.")
                    if ontology.get("peers"):
                        onto_parts.append(f"Department peers: {', '.join(ontology['peers'])}.")
                    if vessel:
                        alert = vessel.get("alert_condition", "GREEN")
                        onto_parts.append(
                            f"Ship status: {vessel.get('name', 'ProbOS')} "
                            f"v{vessel.get('version', '?')} — Alert Condition {alert}."
                        )
                    # AD-648: Capability grounding — what this post actually does
                    caps = ontology.get("capabilities", [])
                    if caps:
                        cap_lines = [f"- {c['summary']}" for c in caps]
                        onto_parts.append(
                            "Your post capabilities (what you actually do):\n"
                            + "\n".join(cap_lines)
                        )
                    negatives = ontology.get("does_not_have", [])
                    if negatives:
                        neg_lines = [f"- {n}" for n in negatives]
                        onto_parts.append(
                            "You do NOT have (do not claim or reference these):\n"
                            + "\n".join(neg_lines)
                        )
                    state["_ontology_context"] = "\n".join(onto_parts)
        except Exception:
            logger.debug("AD-646: Ontology baseline computation failed", exc_info=True)

        # 5. Source attribution (simplified — no authority classification)
        memories = observation.get("recent_memories", [])
        _sources: list[str] = []
        if memories and isinstance(memories, list):
            _sources.append(f"episodic memory ({len(memories)} episodes)")
        if not _sources:
            _sources.append("training knowledge only")
        state["_source_attribution_text"] = (
            f"[Source awareness: Your response draws on: {', '.join(_sources)}. "
            f"Source quality: unknown.]"
        )

        # 6. Confabulation guard (generic — no authority)
        state["_confabulation_guard"] = self._confabulation_guard(None)

        # 7. No-memories flag
        if not memories or not isinstance(memories, list):
            state["_no_episodic_memories"] = (
                "You have no stored episodic memories yet. "
                "Do not reference or invent past experiences you do not have."
            )

        # 8. Communication proficiency (AD-625) — self-contained
        comm_guidance = self._get_comm_proficiency_guidance()
        if comm_guidance:
            state["_comm_proficiency"] = comm_guidance

        # 9. Cold-start note (BF-102) — sync check
        _rt_cs = getattr(self, '_runtime', None)
        if _rt_cs and getattr(_rt_cs, 'is_cold_start', False):
            state["_cold_start_note"] = (
                "SYSTEM NOTE: This is a fresh start. You have no prior "
                "episodic memories. Do not reference or invent past experiences."
            )

        # 10. Rich source attribution override (AD-568d)
        _attr = observation.get("_source_attribution")
        if _attr:
            try:
                _sources_present: list[str] = []
                if _attr.episodic_count > 0:
                    _sources_present.append(f"episodic memory ({_attr.episodic_count} episodes)")
                if _attr.procedural_count > 0:
                    _sources_present.append(f"learned procedures ({_attr.procedural_count})")
                if _attr.oracle_used:
                    _sources_present.append("ship's records")
                if not _sources_present:
                    _sources_present.append("training knowledge only")
                state["_source_attribution_text"] = (
                    f"<source_awareness>Your response draws on: {', '.join(_sources_present)}. "
                    f"Primary basis: {_attr.primary_source.value}.</source_awareness>"
                )
            except Exception:
                logger.debug("AD-646b: Rich source attribution failed", exc_info=True)

        # 11. Self-recognition (AD-575) — sync regex
        _content = observation.get("context", "")
        if _content:
            self_cue = self._detect_self_in_content(_content)
            if self_cue:
                state["_self_recognition_cue"] = self_cue

        return state

    def _build_cognitive_extensions(self, context_parts: dict) -> dict[str, str]:
        """AD-646: Context-parts-dependent cognitive state — proactive path only.

        Returns keys that override baseline with richer versions when
        context_parts is available (populated by proactive.py _gather_context()).
        """
        state: dict[str, str] = {}

        # 1. Self-monitoring (AD-504/506a) — requires context_parts
        self_mon = context_parts.get("self_monitoring")
        if self_mon:
            sm_parts: list[str] = []

            # Cognitive zone
            zone = self_mon.get("cognitive_zone")
            zone_note = self_mon.get("zone_note")
            if zone:
                sm_parts.append(f"<cognitive_zone>{zone.upper()}</cognitive_zone>")
                if zone_note:
                    sm_parts.append(zone_note)

            # Recent posts
            recent_posts = self_mon.get("recent_posts")
            if recent_posts:
                sm_parts.append("Your recent posts (review before adding):")
                for p in recent_posts:
                    age_str = f"[{p['age']} ago]" if p.get("age") else ""
                    sm_parts.append(f"  - {age_str} {p['body']}")

            # Self-similarity
            sim = self_mon.get("self_similarity")
            if sim is not None:
                sm_parts.append(f"Self-similarity across recent posts: {sim:.2f}")
                if sim >= 0.5:
                    sm_parts.append(
                        "WARNING: Your recent posts show high similarity. "
                        "Before posting, ensure you have GENUINELY NEW information. "
                        "If not, respond with [NO_RESPONSE]."
                    )
                elif sim >= 0.3:
                    sm_parts.append(
                        "Note: Some similarity in your recent posts. "
                        "Consider whether you are adding new insight or restating."
                    )

            # Cooldown
            if self_mon.get("cooldown_increased"):
                sm_parts.append(
                    "Your proactive cooldown has been increased due to rising similarity. "
                    "This is pacing, not punishment — take time to find fresh perspectives."
                )
            if self_mon.get("cooldown_reason"):
                sm_parts.append(f"  Counselor note: {self_mon['cooldown_reason']}")

            # Memory state awareness
            mem_state = self_mon.get("memory_state")
            if mem_state:
                count = mem_state.get("episode_count", 0)
                lifecycle = mem_state.get("lifecycle", "")
                uptime_hrs = mem_state.get("uptime_hours", 0)
                if count < 5 and lifecycle != "reset" and uptime_hrs > 1:
                    sm_parts.append(
                        f"Note: You have {count} episodic memories, but the system has been "
                        f"running for {uptime_hrs:.1f}h. Other crew may have richer histories. "
                        "Do not generalize from your own sparse memory to the crew's state."
                    )

            # Notebook index
            nb_index = self_mon.get("notebook_index")
            if nb_index:
                topics = ", ".join(
                    f"{e['topic']} (updated {e['updated']})" if e.get("updated") else e["topic"]
                    for e in nb_index
                )
                sm_parts.append(f"Your notebooks: [{topics}]")
                sm_parts.append(
                    "Use [NOTEBOOK topic-slug] to update. "
                    "Use [READ_NOTEBOOK topic-slug] to review a notebook next cycle."
                )

            # Notebook content
            nb_content = self_mon.get("notebook_content")
            if nb_content:
                sm_parts.append(f'<notebook topic="{nb_content["topic"]}">')
                sm_parts.append(nb_content["snippet"])
                sm_parts.append("</notebook>")

            if sm_parts:
                state["_self_monitoring"] = "\n".join(sm_parts)

        # 2. Source attribution — override baseline with authority-aware version
        memories = context_parts.get("recent_memories", [])
        _framing = context_parts.get("_source_framing")
        if memories or _framing:
            _sources: list[str] = []
            if memories:
                _sources.append(f"episodic memory ({len(memories)} episodes)")
            if not _sources:
                _sources.append("training knowledge only")
            _authority = getattr(_framing, 'authority', None) if _framing else None
            _auth_label = getattr(_authority, 'value', 'unknown') if _authority else "unknown"
            state["_source_attribution_text"] = (
                f"[Source awareness: Your response draws on: {', '.join(_sources)}. "
                f"Source quality: {_auth_label}.]"
            )

        # 3. Introspective telemetry (AD-588)
        telemetry = context_parts.get("introspective_telemetry")
        if telemetry:
            state["_introspective_telemetry"] = telemetry

        # 4. Ontology identity grounding — override baseline from context_parts
        ontology = context_parts.get("ontology")
        if ontology:
            onto_parts: list[str] = []
            identity = ontology.get("identity", {})
            dept = ontology.get("department", {})
            vessel = ontology.get("vessel", {})
            onto_parts.append(
                f"You are {identity.get('callsign', '?')}, "
                f"{identity.get('post', '?')} in {dept.get('name', '?')} department."
            )
            if ontology.get("reports_to"):
                onto_parts.append(f"You report to {ontology['reports_to']}.")
            if ontology.get("direct_reports"):
                onto_parts.append(f"Your direct reports: {', '.join(ontology['direct_reports'])}.")
            if ontology.get("peers"):
                onto_parts.append(f"Department peers: {', '.join(ontology['peers'])}.")
            if vessel:
                alert = vessel.get("alert_condition", "GREEN")
                onto_parts.append(
                    f"Ship status: {vessel.get('name', 'ProbOS')} "
                    f"v{vessel.get('version', '?')} — Alert Condition {alert}."
                )
            state["_ontology_context"] = "\n".join(onto_parts)

        # 5. Orientation supplement (AD-567g)
        orientation = context_parts.get("orientation_supplement")
        if orientation:
            state["_orientation_supplement"] = orientation

        # 6. Confabulation guard — override baseline with authority-calibrated version
        _authority_val = getattr(_framing, 'authority', None) if _framing else None
        if _authority_val is not None:
            state["_confabulation_guard"] = self._confabulation_guard(_authority_val)

        # 7. No-memories flag — override baseline based on context_parts memories
        if memories:
            # Has memories — signal removal of baseline's no-memories flag
            state["_no_episodic_memories"] = None  # type: ignore[assignment]
        elif not memories and _framing is not None:
            # context_parts present but no memories — set flag
            state["_no_episodic_memories"] = (
                "You have no stored episodic memories yet. "
                "Do not reference or invent past experiences you do not have."
            )

        return state

    def _build_cognitive_state(self, context_parts: dict, observation: dict | None = None) -> dict[str, str]:
        """AD-644 Phase 2 / AD-646: Populate innate faculty observation keys for chain prompts.

        Delegates to baseline (always runs) + extensions (context_parts-dependent).
        Baseline provides agent-intrinsic self-knowledge; extensions override with
        richer versions when proactive.py's context_parts is available.

        AD-666: This is the interoception hub of the Agent Sensorium — the agent's
        structured self-state snapshot. See SENSORIUM_REGISTRY for the full inventory.
        """
        state = self._build_cognitive_baseline(observation or {})
        if context_parts:
            extensions = self._build_cognitive_extensions(context_parts)
            # Extensions can mark keys for removal by setting value to None
            for key, val in extensions.items():
                if val is None:
                    state.pop(key, None)
                else:
                    state[key] = val
        return state

    def _track_sensorium_budget(
        self,
        cognitive_state: dict[str, str],
        situation: dict[str, str],
    ) -> int:
        """AD-666: Measure sensorium injection size and emit a warning event over budget."""
        cognitive_chars = sum(
            len(value) for value in cognitive_state.values() if isinstance(value, str)
        )
        situation_chars = sum(
            len(value) for value in situation.values() if isinstance(value, str)
        )
        total_chars = cognitive_chars + situation_chars

        runtime = getattr(self, "_runtime", None)
        threshold = 10000
        sensorium_config = getattr(getattr(runtime, "config", None), "sensorium", None)
        if sensorium_config is not None:
            if not getattr(sensorium_config, "enabled", True):
                return total_chars
            configured_threshold = getattr(sensorium_config, "token_budget_warning", threshold)
            if isinstance(configured_threshold, int):
                threshold = configured_threshold

        if total_chars > threshold:
            agent_id = getattr(self, "id", "unknown")
            callsign = self._resolve_callsign() or agent_id
            logger.warning(
                "AD-666: Sensorium budget exceeded for %s: %d chars (threshold: %d). "
                "Cognitive state: %d chars, situation: %d chars. "
                "Context may be crowding out instruction space.",
                callsign,
                total_chars,
                threshold,
                cognitive_chars,
                situation_chars,
            )
            if runtime and hasattr(runtime, "emit_event"):
                runtime.emit_event(
                    EventType.SENSORIUM_BUDGET_EXCEEDED,
                    {
                        "agent_id": agent_id,
                        "callsign": callsign,
                        "total_chars": total_chars,
                        "threshold": threshold,
                        "cognitive_state_chars": cognitive_chars,
                        "situation_chars": situation_chars,
                    },
                )

        return total_chars

    def _build_situation_awareness(self, context_parts: dict) -> dict[str, str]:
        """AD-644 Phase 3: Extract situation awareness data for chain prompts.

        Returns a dict of observation keys → rendered strings. Called from
        _execute_chain_with_intent_routing() after Phase 2 cognitive state.

        These are environmental percepts — what's happening around the agent.
        The one-shot path renders these inline in _build_user_message().
        This method extracts them into observation keys so ANALYZE can
        render the current situation.
        """
        state: dict[str, str] = {}

        # 1. Ward Room activity (AD-413) — dept + all-hands + recreation
        wr_activity = context_parts.get("ward_room_activity", [])
        if wr_activity:
            wr_lines: list[str] = []
            wr_lines.append("Recent Ward Room discussion:")
            for a in wr_activity:
                prefix = "[thread]" if a.get("type") == "thread" else "[reply]"
                ids = ""
                if a.get("thread_id"):
                    ids += f" thread:{a['thread_id'][:8]}"
                if a.get("post_id"):
                    ids += f" post:{a['post_id'][:8]}"
                score = a.get("net_score", 0)
                score_str = f" [+{score}]" if score > 0 else f" [{score}]" if score < 0 else ""
                channel = f" ({a['channel']})" if a.get("channel") else ""
                wr_lines.append(
                    f"  - {prefix}{ids}{score_str} {a.get('author', '?')}{channel}: "
                    f"{a.get('body', '?')}"
                )
            state["_ward_room_activity"] = "\n".join(wr_lines)

        # 2. Recent bridge alerts
        alerts = context_parts.get("recent_alerts", [])
        if alerts:
            alert_lines = ["Recent bridge alerts:"]
            for a in alerts:
                alert_lines.append(
                    f"  - [{a.get('severity', '?')}] {a.get('title', '?')} "
                    f"(from {a.get('source', '?')})"
                )
            state["_recent_alerts"] = "\n".join(alert_lines)

        # 3. Recent system events
        events = context_parts.get("recent_events", [])
        if events:
            event_lines = ["Recent system events:"]
            for e in events:
                event_lines.append(
                    f"  - [{e.get('category', '?')}] {e.get('event', '?')}"
                )
            state["_recent_events"] = "\n".join(event_lines)

        # 4. Infrastructure status (AD-576)
        infra = context_parts.get("infrastructure_status")
        if infra:
            llm_status = infra.get("llm_status", "unknown")
            state["_infrastructure_status"] = (
                f"[INFRASTRUCTURE NOTE: Communications array {llm_status}]\n"
                f"{infra.get('message', '')}"
            )

        # 5. Subordinate stats (AD-630) — Chiefs only
        sub_stats = context_parts.get("subordinate_stats")
        if sub_stats:
            sub_lines = ["<subordinate_activity>"]
            for callsign, stats in sub_stats.items():
                sub_lines.append(
                    f"  {callsign}: {stats['posts_total']} posts, "
                    f"{stats['endorsements_given']} endorsements given, "
                    f"{stats['endorsements_received']} endorsements received, "
                    f"credibility {stats['credibility_score']:.2f}"
                )
            sub_lines.append("</subordinate_activity>")
            state["_subordinate_stats"] = "\n".join(sub_lines)

        # 6. Cold-start system note (BF-034)
        system_note = context_parts.get("system_note")
        if system_note:
            state["_cold_start_note"] = system_note

        # 7. Active game state (BF-110)
        active_game = context_parts.get("active_game")
        if active_game:
            game_lines = [
                f"You are playing {active_game['game_type']} against "
                f"{active_game['opponent']}. "
                f"Moves so far: {active_game['moves_count']}.",
                f"\nCurrent board:\n```\n{active_game['board']}\n```",
            ]
            if active_game["is_my_turn"]:
                game_lines.append(
                    f"**It is YOUR turn.** Valid moves: "
                    f"{', '.join(str(m) for m in active_game['valid_moves'])}. "
                    f"Reply with [MOVE position] to play."
                )
            else:
                game_lines.append("Waiting for your opponent to move.")
            state["_active_game"] = "\n".join(game_lines)

        return state

    # AD-588: Introspective self-query detection patterns
    _INTROSPECTIVE_PATTERNS: ClassVar[list[re.Pattern]] = [
        re.compile(r"\b(?:your|you)\b.*\b(?:memor(?:y|ies)|remember|recall|forget|episode)\b", re.IGNORECASE),
        re.compile(r"\b(?:your|you)\b.*\b(?:trust|reputation|reliab|scor)\b", re.IGNORECASE),
        re.compile(r"\b(?:how (?:are|do) you|how.*feel|what.*(?:like for you)|your (?:state|status))\b", re.IGNORECASE),
        re.compile(r"\b(?:how (?:do|does) your|your (?:brain|mind|cognit|process|think))\b", re.IGNORECASE),
        re.compile(r"\b(?:stasis|offline|sleep|shutdown|dream|while.*(?:away|gone|down))\b", re.IGNORECASE),
        re.compile(r"\b(?:tell me about yourself|who are you|what are you|describe yourself)\b", re.IGNORECASE),
    ]

    @staticmethod
    def _is_introspective_query(text: str) -> bool:
        """AD-588: Detect introspective questions in captain/crew messages."""
        if not text:
            return False
        for pattern in CognitiveAgent._INTROSPECTIVE_PATTERNS:
            if pattern.search(text):
                return True
        return False

    def _build_crew_complement(self) -> str:
        """AD-513: Build compact crew complement for cognitive grounding.

        Prevents confabulation by anchoring agents to the actual crew roster.
        Injected into all prompt paths via _build_temporal_context().
        """
        rt = getattr(self, '_runtime', None)
        if not rt or not getattr(rt, 'ontology', None):
            return ""

        try:
            manifest = rt.ontology.get_crew_manifest(
                callsign_registry=getattr(rt, 'callsign_registry', None),
            )
        except Exception:
            return ""

        if not manifest:
            return ""

        self_atype = getattr(self, 'agent_type', '')
        dept_groups: dict[str, list[str]] = {}
        for entry in manifest:
            if entry["agent_type"] == self_atype:
                continue
            dept = (entry.get("department") or "bridge").capitalize()
            dept_groups.setdefault(dept, []).append(entry["callsign"])

        if not dept_groups:
            return ""

        lines = ["=== SHIP'S COMPLEMENT (these are the ONLY crew aboard) ==="]
        for dept_name in sorted(dept_groups):
            members = ", ".join(sorted(dept_groups[dept_name]))
            lines.append(f"  {dept_name}: {members}")
        lines.append(
            "Do NOT reference crew members who are not listed above. "
            "If you are uncertain whether someone is aboard, verify against this roster."
        )
        return "\n".join(lines)

    @staticmethod
    def _confabulation_guard(authority: str | None) -> str:
        """Return AD-592 confabulation guard instruction calibrated by source authority.

        Three tiers of guard strength:
        - AUTHORITATIVE: light touch — memories are high quality, still warn about numbers
        - SUPPLEMENTARY/None: standard guard — warn about numbers + orientation priority
        - PERIPHERAL: strong guard — warn about numbers + orientation priority + uncertainty
        """
        # Import here to avoid circular dependency at module level
        from probos.cognitive.source_governance import SourceAuthority

        base = (
            "IMPORTANT: Do NOT fabricate specific numbers, durations, measurements, or statistics "
            "from these fragments. If an exact value is not in your memories, say you do not have that data."
        )
        orientation_priority = (
            " When orientation or system data conflicts with your memories, "
            "orientation data is authoritative — cite it, do not estimate."
        )
        # BF-148: temporal preference for contradictory memories (AGM Belief Revision)
        temporal_preference = (
            " When memories contain conflicting values for the same measurement, "
            "prefer the most recent observation."
        )

        if authority == SourceAuthority.AUTHORITATIVE:
            # High-quality memories — still guard against number fabrication.
            # BF-159: Include temporal preference even for AUTHORITATIVE.
            # Temporal contradictions (same metric, different timestamps) are
            # valid regardless of anchor quality. AGM Belief Revision applies
            # universally — newer observations supersede older ones.
            return base + temporal_preference
        elif authority == SourceAuthority.PERIPHERAL:
            # Low-quality memories — full guard + uncertainty mandate
            return base + orientation_priority + temporal_preference + " State uncertainty explicitly."
        else:
            # SUPPLEMENTARY or no framing (fallback) — standard guard
            return base + orientation_priority + temporal_preference

    def _format_memory_section(self, memories: list[dict], source_framing: Any = None) -> list[str]:
        """Format recalled episodes with anchor context headers (AD-567b/568c)."""
        # AD-568c: Use source-authority-calibrated framing if available
        if source_framing:
            lines = [
                source_framing.header,
                source_framing.instruction,
            ]
            # AD-592: Authority-calibrated confabulation guard
            lines.append(self._confabulation_guard(source_framing.authority))
            lines.extend([
                "Markers: [direct] = you experienced it, [secondhand] = you heard about it.",
                "[verified] = corroborated by ship's log, [unverified] = not yet corroborated.",
                "",
            ])
        else:
            lines = [
                "=== SHIP MEMORY (your experiences aboard this vessel) ===",
                "These are YOUR experiences. Do NOT confuse with training knowledge.",
                self._confabulation_guard(None),
                "Markers: [direct] = you experienced it, [secondhand] = you heard about it.",
                "[verified] = corroborated by ship's log, [unverified] = not yet corroborated.",
                "",
            ]
        for mem in memories:
            # Anchor header line (AD-567b)
            anchor_parts = []
            if mem.get("age"):
                anchor_parts.append(f"{mem['age']} ago")
            if mem.get("anchor_channel"):
                anchor_parts.append(mem["anchor_channel"])
            if mem.get("anchor_department"):
                anchor_parts.append(f"{mem['anchor_department']} dept")
            if mem.get("anchor_participants"):
                anchor_parts.append(f"with {mem['anchor_participants']}")
            if mem.get("anchor_trigger"):
                anchor_parts.append(f"re: {mem['anchor_trigger']}")

            source = mem.get("source", "direct")
            verified = "verified" if mem.get("verified") else "unverified"
            header = f"  [{source} | {verified}]"
            if anchor_parts:
                header += f" [{' | '.join(anchor_parts)}]"

            lines.append(header)
            lines.append(f"    {mem.get('input', '') or mem.get('reflection', '')}")
        lines.append("")
        lines.append("=== END SHIP MEMORY ===")
        return lines

    async def _build_user_message(self, observation: dict) -> str:
        """Build the user message from the observation dict.
        Override in subclasses for custom formatting.

        AD-666 Injection Ordering Audit:
        Chain path: cognitive state, situation awareness, sensorium budget tracking,
        then chain ANALYZE prompt rendering. DM path: temporal awareness, cognitive
        zone, telemetry, working memory, episodic memories, Oracle context, source
        attribution, session history, active game context, then Captain message.
        WR path: channel/thread header, temporal awareness, cognitive zone, DM
        self-monitoring, telemetry, working memory, episodic memories,
        self-recognition, thread context, then author message.
        """
        intent_name = observation.get("intent", "unknown")
        params = observation.get("params", {})

        # AD-397: direct_message — conversational context for 1:1 sessions
        if intent_name == "direct_message":
            parts: list[str] = []

            # AD-502: Temporal awareness header
            temporal_ctx = self._build_temporal_context()
            if temporal_ctx:
                parts.append("--- Temporal Awareness ---")
                parts.append(temporal_ctx)
                parts.append("---")
                parts.append("")

            # AD-588: Cognitive zone awareness in DM path
            _zone = None
            _wm_zone = getattr(self, '_working_memory', None)
            if _wm_zone and hasattr(_wm_zone, 'get_cognitive_zone'):
                _zone = _wm_zone.get_cognitive_zone()
            if _zone and _zone != "green":
                parts.append(f"<cognitive_zone>{_zone.upper()}</cognitive_zone>")
                parts.append("")

            # AD-588: Introspective telemetry for self-referential queries
            captain_text = params.get("text", "")
            _telemetry_svc = getattr(self._runtime, '_introspective_telemetry', None) if self._runtime else None
            if _telemetry_svc and self._is_introspective_query(captain_text):
                try:
                    _agent_id = getattr(self, 'sovereign_id', None) or self.id
                    _snapshot = await _telemetry_svc.get_full_snapshot(_agent_id)
                    _telemetry_text = _telemetry_svc.render_telemetry_context(_snapshot)
                    if _telemetry_text:
                        parts.append(_telemetry_text)
                        parts.append("")
                    # AD-589: Cache for post-decision faithfulness cross-check
                    _wm = getattr(self, '_working_memory', None)
                    if _wm and hasattr(_wm, 'set_telemetry_snapshot'):
                        _wm.set_telemetry_snapshot(_snapshot)
                except Exception:
                    logger.debug("AD-588: telemetry injection failed for DM", exc_info=True)

            # AD-573: Working memory — unified situational awareness
            _wm = getattr(self, '_working_memory', None)
            wm_context = _wm.render_context() if _wm else ""
            if wm_context:
                parts.append(wm_context)
                parts.append("")

            # AD-430c / AD-540: Episodic memory with provenance boundary
            memories = observation.get("recent_memories", [])
            if memories:
                _framing = observation.get("_source_framing")
                parts.extend(self._format_memory_section(memories, source_framing=_framing))
                parts.append("")

            # AD-568a: Oracle Service cross-tier context (ORACLE tier + DEEP strategy only)
            if observation.get("_oracle_context"):
                parts.append(
                    "=== CROSS-TIER KNOWLEDGE (Ship's Records + Operational State) ===\n"
                    "These are NOT your personal experiences. They are from the ship's shared "
                    "knowledge stores. Treat as reference material, not memory."
                )
                parts.append(observation["_oracle_context"])
                parts.append("=== END CROSS-TIER KNOWLEDGE ===")
                parts.append("")

            # AD-568d: Ambient source attribution tag (cognitive proprioception)
            _attr = observation.get("_source_attribution")
            if _attr:
                _sources_present = []
                if _attr.episodic_count > 0:
                    _sources_present.append(f"episodic memory ({_attr.episodic_count} episodes)")
                if _attr.procedural_count > 0:
                    _sources_present.append(f"learned procedures ({_attr.procedural_count})")
                if _attr.oracle_used:
                    _sources_present.append("ship's records")
                if not _sources_present:
                    _sources_present.append("training knowledge only")
                parts.append(
                    f"<source_awareness>Your response draws on: {', '.join(_sources_present)}. "
                    f"Primary basis: {_attr.primary_source.value}.</source_awareness>"
                )
                parts.append("")

            session_history = params.get("session_history", [])
            if session_history:
                parts.append("Previous conversation:")
                for entry in session_history:
                    role = entry.get("role", "unknown")
                    text = entry.get("text", "")
                    parts.append(f"  {role}: {text}")
                parts.append("")

            # AD-572: Active game state awareness in DM path
            active_game_ctx = self._build_active_game_context()
            if active_game_ctx:
                parts.append(active_game_ctx)
                parts.append("")

            parts.append(f"Captain says: {params.get('text', '')}")
            return "\n".join(parts)

        # AD-407b: ward_room_notification — thread context for Ward Room
        if intent_name == "ward_room_notification":
            channel_name = params.get("channel_name", "")
            author_callsign = params.get("author_callsign", "unknown")
            title = params.get("title", "")
            context = observation.get("context", "")

            wr_parts: list[str] = []
            wr_parts.append(f"[Ward Room — #{channel_name}]")
            wr_parts.append(f"Thread: {title}")

            # AD-502: Temporal awareness header
            temporal_ctx = self._build_temporal_context()
            if temporal_ctx:
                wr_parts.append("")
                wr_parts.append("--- Temporal Awareness ---")
                wr_parts.append(temporal_ctx)
                wr_parts.append("---")

            # AD-588: Cognitive zone awareness in Ward Room path
            _zone = None
            _wm_zone = getattr(self, '_working_memory', None)
            if _wm_zone and hasattr(_wm_zone, 'get_cognitive_zone'):
                _zone = _wm_zone.get_cognitive_zone()
            if _zone and _zone != "green":
                wr_parts.append("")
                wr_parts.append(f"<cognitive_zone>{_zone.upper()}</cognitive_zone>")

            # AD-623: DM self-monitoring — agents responding to DM threads
            # see their own repetition in real time
            if channel_name.startswith("dm-"):
                _dm_self_mon = await self._build_dm_self_monitoring(
                    params.get("thread_id", ""),
                )
                if _dm_self_mon:
                    wr_parts.append("")
                    wr_parts.append(_dm_self_mon)

            # AD-588: Introspective telemetry for self-referential ward room posts
            _wr_text = f"{params.get('title', '')} {params.get('text', '')}".strip()
            _telemetry_svc = getattr(self._runtime, '_introspective_telemetry', None) if self._runtime else None
            if _telemetry_svc and self._is_introspective_query(_wr_text):
                try:
                    _agent_id = getattr(self, 'sovereign_id', None) or self.id
                    _snapshot = await _telemetry_svc.get_full_snapshot(_agent_id)
                    _telemetry_text = _telemetry_svc.render_telemetry_context(_snapshot)
                    if _telemetry_text:
                        wr_parts.append("")
                        wr_parts.append(_telemetry_text)
                    # AD-589: Cache for post-decision faithfulness cross-check
                    _wm = getattr(self, '_working_memory', None)
                    if _wm and hasattr(_wm, 'set_telemetry_snapshot'):
                        _wm.set_telemetry_snapshot(_snapshot)
                except Exception:
                    logger.debug("AD-588: telemetry injection failed for WR", exc_info=True)

            # AD-573: Working memory — unified situational awareness
            _wm = getattr(self, '_working_memory', None)
            wm_context = _wm.render_context() if _wm else ""
            if wm_context:
                wr_parts.append("")
                wr_parts.append(wm_context)

            # BF-102: Cold-start system note in ward room context
            rt = getattr(self, '_runtime', None)
            if rt and getattr(rt, 'is_cold_start', False):
                wr_parts.append("")
                wr_parts.append(
                    "SYSTEM NOTE: This is a fresh start. You have no prior "
                    "episodic memories. Do not reference or invent past experiences."
                )

            # AD-430c / AD-540: Episodic memory with provenance boundary
            memories = observation.get("recent_memories", [])
            if memories:
                wr_parts.append("")
                _framing = observation.get("_source_framing")
                wr_parts.extend(self._format_memory_section(memories, source_framing=_framing))

            # AD-568a: Oracle Service cross-tier context
            if observation.get("_oracle_context"):
                wr_parts.append("")
                wr_parts.append(
                    "=== CROSS-TIER KNOWLEDGE (Ship's Records + Operational State) ===\n"
                    "These are NOT your personal experiences. They are from the ship's shared "
                    "knowledge stores. Treat as reference material, not memory."
                )
                wr_parts.append(observation["_oracle_context"])
                wr_parts.append("=== END CROSS-TIER KNOWLEDGE ===")

            # AD-568d: Ambient source attribution tag (cognitive proprioception)
            _attr = observation.get("_source_attribution")
            if _attr:
                _sources_present = []
                if _attr.episodic_count > 0:
                    _sources_present.append(f"episodic memory ({_attr.episodic_count} episodes)")
                if _attr.procedural_count > 0:
                    _sources_present.append(f"learned procedures ({_attr.procedural_count})")
                if _attr.oracle_used:
                    _sources_present.append("ship's records")
                if not _sources_present:
                    _sources_present.append("training knowledge only")
                wr_parts.append("")
                wr_parts.append(
                    f"<source_awareness>Your response draws on: {', '.join(_sources_present)}. "
                    f"Primary basis: {_attr.primary_source.value}.</source_awareness>"
                )

            # AD-626/AD-631: Generic task-framed skill injection (with proficiency context)
            _aug_skill = observation.get("_augmentation_skill_instructions")
            if _aug_skill and context:
                _meta = self._extract_thread_metadata(context)
                _prof_ctx = self._get_comm_proficiency_guidance() or ""
                wr_parts.extend(self._frame_task_with_skill(
                    _aug_skill, "Process Ward Room Thread", _meta,
                    proficiency_context=_prof_ctx,
                ))

            if context:
                wr_parts.append(f"\nConversation so far:\n{context}")

            # AD-575: Self-recognition in Ward Room threads
            self_cue = self._detect_self_in_content(context)
            if self_cue:
                wr_parts.append(self_cue)

            # AD-407d: Distinguish Captain vs crew member posts
            author_id = params.get("author_id", "")
            was_mentioned = params.get("was_mentioned", False)

            if author_id == "captain":
                wr_parts.append(f"\nThe Captain posted the above.")
            else:
                wr_parts.append(f"\n{author_callsign} posted the above.")

            # BF-157: @mentioned agents must respond — they were directly addressed.
            if was_mentioned:
                wr_parts.append(
                    "You were directly @mentioned in this post. A response is expected. "
                    "Address the question or request from your area of expertise. "
                    "Be concise and helpful."
                )
            else:
                wr_parts.append("Respond naturally as yourself. Share your perspective if you have something meaningful to contribute.")
                wr_parts.append("If this topic is outside your expertise or you have nothing to add, respond with exactly: [NO_RESPONSE]")
            return "\n".join(wr_parts)

        # Phase 28b: proactive_think — idle review cycle
        if intent_name == "proactive_think":
            context_parts = params.get("context_parts", {})
            trust_score = params.get("trust_score", 0.5)
            agency_level = params.get("agency_level", "suggestive")
            duty = params.get("duty")  # AD-419: may be None

            pt_parts: list[str] = []

            if duty:
                # AD-419: Duty cycle — agent has a scheduled task
                pt_parts.append(f"[Duty Cycle: {duty.get('description', duty.get('duty_id', 'unknown'))}]")
                pt_parts.append(f"Your trust: {trust_score} | Agency: {agency_level} | Rank: {params.get('rank', 'unknown')}")
                pt_parts.append("")
                pt_parts.append("This is a scheduled duty. Perform your assigned task and report your findings.")
                pt_parts.append("")
            else:
                # Free-form think — no duty due, requires justification
                pt_parts.append("[Proactive Review — No Scheduled Duty]")
                pt_parts.append(f"Your trust: {trust_score} | Agency: {agency_level} | Rank: {params.get('rank', 'unknown')}")
                pt_parts.append("")
                pt_parts.append("You have no scheduled duty at this time. You may share an observation")
                pt_parts.append("ONLY if you notice something genuinely noteworthy or actionable.")
                pt_parts.append("If you do post, include a brief justification for why it matters now.")
                pt_parts.append("Silence is professionalism — [NO_RESPONSE] is the expected default.")
                pt_parts.append("Do not comment on your own posting patterns or observation frequency.")
                pt_parts.append("")

            # AD-502: Temporal awareness header
            temporal_ctx = self._build_temporal_context()
            if temporal_ctx:
                pt_parts.append("--- Temporal Awareness ---")
                pt_parts.append(temporal_ctx)
                pt_parts.append("---")
                pt_parts.append("")

            # AD-573: Working memory — supplements proactive context
            _wm = getattr(self, '_working_memory', None)
            wm_context = _wm.render_context(budget=1500) if _wm else ""
            if wm_context:
                pt_parts.append(wm_context)
                pt_parts.append("")

            # BF-034: Cold-start system note
            system_note = context_parts.get("system_note")
            if system_note:
                pt_parts.append(system_note)
                pt_parts.append("")

            # AD-576: Infrastructure awareness
            infra_status = context_parts.get("infrastructure_status")
            if infra_status:
                llm_status = infra_status.get("llm_status", "unknown")
                pt_parts.append(f"[INFRASTRUCTURE NOTE: Communications array {llm_status}]")
                pt_parts.append(infra_status.get("message", ""))
                pt_parts.append("")

            # AD-429: Ontology identity grounding
            ontology = context_parts.get("ontology")
            if ontology:
                identity = ontology.get("identity", {})
                dept = ontology.get("department", {})
                vessel = ontology.get("vessel", {})
                pt_parts.append(f"You are {identity.get('callsign', '?')}, {identity.get('post', '?')} in {dept.get('name', '?')} department.")
                if ontology.get("reports_to"):
                    pt_parts.append(f"You report to {ontology['reports_to']}.")
                if ontology.get("direct_reports"):
                    pt_parts.append(f"Your direct reports: {', '.join(ontology['direct_reports'])}.")
                if ontology.get("peers"):
                    pt_parts.append(f"Department peers: {', '.join(ontology['peers'])}.")
                if vessel:
                    alert = vessel.get("alert_condition", "GREEN")
                    pt_parts.append(f"Ship status: {vessel.get('name', 'ProbOS')} v{vessel.get('version', '?')} — Alert Condition {alert}.")
                pt_parts.append("")

            # AD-630: Subordinate communication stats for Chiefs
            sub_stats = context_parts.get("subordinate_stats")
            if sub_stats:
                pt_parts.append("<subordinate_activity>")
                for callsign, stats in sub_stats.items():
                    pt_parts.append(
                        f"  {callsign}: {stats['posts_total']} posts, "
                        f"{stats['endorsements_given']} endorsements given, "
                        f"{stats['endorsements_received']} endorsements received, "
                        f"credibility {stats['credibility_score']:.2f}"
                    )
                pt_parts.append("</subordinate_activity>")
                pt_parts.append("")

            # AD-567g: Diminishing orientation supplement for young agents
            orientation_supp = context_parts.get("orientation_supplement")
            if orientation_supp:
                pt_parts.append(orientation_supp)
                pt_parts.append("")

            # AD-429b: Skill profile
            skill_profile = context_parts.get("skill_profile")
            if skill_profile:
                pt_parts.append(f"Your skills: {', '.join(skill_profile)}.")
                pt_parts.append("")

            # AD-540: Episodic memory with provenance boundary
            memories = context_parts.get("recent_memories", [])
            if memories:
                _framing = context_parts.get("_source_framing")
                pt_parts.extend(self._format_memory_section(memories, source_framing=_framing))
                pt_parts.append("")
            else:
                pt_parts.append("You have no stored episodic memories yet. Do not reference or invent past experiences you do not have.")
                pt_parts.append("")

            # AD-568d: Ambient source attribution tag (cognitive proprioception)
            _attr = observation.get("_source_attribution")
            if _attr:
                _sources_present = []
                if _attr.episodic_count > 0:
                    _sources_present.append(f"episodic memory ({_attr.episodic_count} episodes)")
                if _attr.procedural_count > 0:
                    _sources_present.append(f"learned procedures ({_attr.procedural_count})")
                if _attr.oracle_used:
                    _sources_present.append("ship's records")
                if not _sources_present:
                    _sources_present.append("training knowledge only")
                pt_parts.append(
                    f"[Source awareness: Your response draws on: {', '.join(_sources_present)}. "
                    f"Primary basis: {_attr.primary_source.value}.]"
                )
                pt_parts.append("")

            # Recent alerts
            alerts = context_parts.get("recent_alerts", [])
            if alerts:
                pt_parts.append("Recent bridge alerts:")
                for a in alerts:
                    pt_parts.append(f"  - [{a.get('severity', '?')}] {a.get('title', '?')} (from {a.get('source', '?')})")
                pt_parts.append("")

            # Recent events
            events = context_parts.get("recent_events", [])
            if events:
                pt_parts.append("Recent system events:")
                for e in events:
                    pt_parts.append(f"  - [{e.get('category', '?')}] {e.get('event', '?')}")
                pt_parts.append("")

            # Recent Ward Room activity (AD-413)
            wr_activity = context_parts.get("ward_room_activity", [])

            # AD-626/AD-631: Generic task-framed skill injection for proactive think
            _aug_skill = observation.get("_augmentation_skill_instructions")
            if _aug_skill and wr_activity:
                _prof_ctx = self._get_comm_proficiency_guidance() or ""
                pt_parts.extend(self._frame_task_with_skill(
                    _aug_skill, "Review Ward Room Activity",
                    proficiency_context=_prof_ctx,
                ))

            if wr_activity:
                pt_parts.append("Recent Ward Room discussion in your department:")
                for a in wr_activity:
                    prefix = "[thread]" if a.get("type") == "thread" else "[reply]"
                    ids = ""
                    if a.get("thread_id"):
                        ids += f" thread:{a['thread_id'][:8]}"
                    if a.get("post_id"):
                        ids += f" post:{a['post_id'][:8]}"
                    score = a.get("net_score", 0)
                    score_str = f" [+{score}]" if score > 0 else f" [{score}]" if score < 0 else ""
                    pt_parts.append(f"  - {prefix}{ids}{score_str} {a.get('author', '?')}: {a.get('body', '?')}")
                pt_parts.append("")

            # BF-110: Active game state — show board so agent knows it's their turn
            active_game = context_parts.get("active_game")
            if active_game:
                pt_parts.append("--- Active Game ---")
                pt_parts.append(
                    f"You are playing {active_game['game_type']} against {active_game['opponent']}. "
                    f"Moves so far: {active_game['moves_count']}."
                )
                pt_parts.append(f"\nCurrent board:\n```\n{active_game['board']}\n```")
                if active_game["is_my_turn"]:
                    pt_parts.append(
                        f"**It is YOUR turn.** Valid moves: {', '.join(str(m) for m in active_game['valid_moves'])}. "
                        f"Reply with [MOVE position] to play."
                    )
                else:
                    pt_parts.append("Waiting for your opponent to move.")
                pt_parts.append("")

            # AD-504: Self-monitoring context
            self_mon = context_parts.get("self_monitoring")
            if self_mon:
                pt_parts.append("")

                # AD-506a: Cognitive zone (before self-monitoring details)
                zone = self_mon.get("cognitive_zone")
                zone_note = self_mon.get("zone_note")
                if zone:
                    pt_parts.append(f"<cognitive_zone>{zone.upper()}</cognitive_zone>")
                    if zone_note:
                        pt_parts.append(zone_note)
                    pt_parts.append("")

                pt_parts.append("<recent_activity>")

                # Recent posts
                recent_posts = self_mon.get("recent_posts")
                if recent_posts:
                    pt_parts.append("Your recent posts (review before adding to the discussion):")
                    for p in recent_posts:
                        age_str = f"[{p['age']} ago]" if p.get("age") else ""
                        pt_parts.append(f"  - {age_str} {p['body']}")

                # Self-similarity
                sim = self_mon.get("self_similarity")
                if sim is not None:
                    pt_parts.append(f"Self-similarity across recent posts: {sim:.2f}")
                    if sim >= 0.5:
                        pt_parts.append(
                            "WARNING: Your recent posts show high similarity. "
                            "Before posting, ensure you have GENUINELY NEW information. "
                            "If not, respond with [NO_RESPONSE]."
                        )
                    elif sim >= 0.3:
                        pt_parts.append(
                            "Note: Some similarity in your recent posts. "
                            "Consider whether you are adding new insight or restating."
                        )

                # Cooldown increased
                if self_mon.get("cooldown_increased"):
                    pt_parts.append(
                        "Your proactive cooldown has been increased due to rising similarity. "
                        "This is pacing, not punishment — take time to find fresh perspectives."
                    )

                # AD-505: Counselor cooldown reason
                if self_mon.get("cooldown_reason"):
                    pt_parts.append(f"  Counselor note: {self_mon['cooldown_reason']}")

                # Memory state awareness
                mem_state = self_mon.get("memory_state")
                if mem_state:
                    count = mem_state.get("episode_count", 0)
                    lifecycle = mem_state.get("lifecycle", "")
                    uptime_hrs = mem_state.get("uptime_hours", 0)
                    if count < 5 and lifecycle != "reset" and uptime_hrs > 1:
                        pt_parts.append(
                            f"Note: You have {count} episodic memories, but the system has been "
                            f"running for {uptime_hrs:.1f}h. Other crew may have richer histories. "
                            "Do not generalize from your own sparse memory to the crew's state."
                        )

                # Notebook index
                nb_index = self_mon.get("notebook_index")
                if nb_index:
                    topics = ", ".join(
                        f"{e['topic']} (updated {e['updated']})" if e.get("updated") else e["topic"]
                        for e in nb_index
                    )
                    pt_parts.append(f"Your notebooks: [{topics}]")
                    pt_parts.append(
                        "Use [NOTEBOOK topic-slug] to update. "
                        "Use [READ_NOTEBOOK topic-slug] to review a notebook next cycle."
                    )

                # Notebook content (from semantic pull or explicit read)
                nb_content = self_mon.get("notebook_content")
                if nb_content:
                    pt_parts.append(f'<notebook topic="{nb_content["topic"]}">')
                    pt_parts.append(nb_content["snippet"])
                    pt_parts.append("</notebook>")

                pt_parts.append("</recent_activity>")
                pt_parts.append("")

            # AD-588: Introspective telemetry snapshot (always available in proactive path)
            introspective_telemetry = context_parts.get("introspective_telemetry")
            if introspective_telemetry:
                pt_parts.append("")
                pt_parts.append(introspective_telemetry)

            if duty:
                pt_parts.append("Compose a Ward Room post with your findings (2-4 sentences).")
                pt_parts.append("If nothing noteworthy to report, respond with exactly: [NO_RESPONSE]")
            else:
                pt_parts.append("If something genuinely warrants attention, compose a brief observation (2-4 sentences).")
                pt_parts.append("Include your justification. Otherwise respond with exactly: [NO_RESPONSE]")
            return "\n".join(pt_parts)

        parts = [f"Intent: {intent_name}"]
        if params:
            parts.append(f"Parameters: {params}")
        if observation.get("context"):
            parts.append(f"Context: {observation['context']}")
        if observation.get("fetched_content"):
            parts.append(f"Fetched content:\n{observation['fetched_content']}")
        # AD-535: Include procedure guidance hints for Level 2 (Guided) replay
        if observation.get("procedure_guidance"):
            parts.append(f"\n--- Suggested approach ---\n{observation['procedure_guidance']}")
        return "\n".join(parts)

    async def _recall_relevant_memories(self, intent: IntentMessage, observation: dict) -> dict:
        """AD-430c: Inject relevant episodic memories into observation for decide().

        Only fires for crew agents on conversational intents. Proactive think
        already gets memory context via _gather_context() — skip to avoid duplication.
        """
        # Skip proactive_think — already has memory context from proactive loop
        if intent.intent == "proactive_think":
            return observation

        # Guard: need runtime + episodic memory + crew check
        if not self._runtime:
            return observation
        if not hasattr(self._runtime, 'episodic_memory') or not self._runtime.episodic_memory:
            return observation
        if not hasattr(self._runtime, 'ontology'):
            return observation
        from probos.crew_utils import is_crew_agent as _is_crew
        if not _is_crew(self, getattr(self._runtime, 'ontology', None)):
            return observation

        # AD-602: Lazy-init question classifier
        if self._question_classifier is None:
            try:
                from probos.cognitive.question_classifier import (
                    QuestionClassifier,
                    RetrievalStrategySelector,
                )

                _qa_config = self._runtime.config.question_adaptive
                if not _qa_config.enabled:
                    self._question_classifier = QuestionClassifier()
                    self._retrieval_strategy_selector = None
                else:
                    self._question_classifier = QuestionClassifier()
                    self._retrieval_strategy_selector = RetrievalStrategySelector(config=_qa_config)
            except Exception:
                logger.debug("AD-602: Question classifier unavailable", exc_info=True)

        # AD-604: Lazy-init spreading activation engine
        if getattr(self, "_spreading_activation", None) is None:
            try:
                _sa_config = self._runtime.config.spreading_activation
                if _sa_config.enabled:
                    from probos.cognitive.spreading_activation import SpreadingActivationEngine

                    self._spreading_activation = SpreadingActivationEngine(
                        config=_sa_config,
                        episodic_memory=self._runtime.episodic_memory,
                    )
            except Exception:
                logger.debug("AD-604: Spreading activation unavailable", exc_info=True)

        try:
            # Build a semantic query from the intent content
            params = observation.get("params", {})
            if intent.intent == "direct_message":
                # AD-584b: Removed BF-029 "Ward Room {callsign}" query prefix.
                # With multi-qa-MiniLM-L6-cos-v1, the QA-trained model bridges
                # question->answer gaps without prefix workarounds.
                captain_text = params.get("text", "")[:200]
                query = captain_text.strip()
            elif intent.intent == "ward_room_notification":
                query = f"{params.get('title', '')} {params.get('text', '')}".strip()[:200]
            else:
                query = intent.context[:200] if intent.context else intent.intent

            if not query:
                return observation

            # AD-602: Classify query and select strategy
            _ad602_strategy = None
            _question_type = None
            if self._question_classifier and self._retrieval_strategy_selector:
                try:
                    _question_type = self._question_classifier.classify(query)
                    _ad602_strategy = self._retrieval_strategy_selector.select_strategy(_question_type)
                    logger.debug(
                        "AD-602: Query classified as %s - strategy: method=%s, k=%d",
                        _question_type.value,
                        _ad602_strategy.recall_method,
                        _ad602_strategy.k,
                    )
                except Exception:
                    logger.debug("AD-602: Classification failed, using default recall", exc_info=True)

            _mem_id = getattr(self, 'sovereign_id', None) or self.id  # AD-441

            # AD-570c: Try anchor-indexed recall for relational queries
            _anchor_episodes = None
            _query_watch_section = ""  # BF-147: propagate for temporal match scoring
            try:
                _anchor_episodes, _query_watch_section = await self._try_anchor_recall(query, _mem_id)
            except Exception:
                logger.debug("AD-570c: Anchor recall failed, falling through to semantic", exc_info=True)

            # AD-567b: Use salience-weighted recall when available
            em = self._runtime.episodic_memory
            trust_net = getattr(self._runtime, 'trust_network', None)
            heb_router = getattr(self._runtime, 'hebbian_router', None)
            mem_cfg = None
            if hasattr(self._runtime, 'config') and hasattr(self._runtime.config, 'memory'):
                mem_cfg = self._runtime.config.memory

            _ad604_results: list[Any] = []
            if (
                _question_type is not None
                and getattr(_question_type, "value", "") == "causal"
                and getattr(self, "_spreading_activation", None) is not None
            ):
                try:
                    _ad604_results = await self._spreading_activation.multi_hop_recall(
                        query,
                        _mem_id,
                        trust_network=trust_net,
                        hebbian_router=heb_router,
                    )
                    if _ad604_results:
                        observation["_ad604_spreading_activation"] = True
                        logger.debug(
                            "AD-604: Used spreading activation for CAUSAL query with %d results",
                            len(_ad604_results),
                        )
                except Exception:
                    logger.debug("AD-604: Spreading activation failed; falling back to standard recall", exc_info=True)

            # AD-620: Resolve recall tier from rank + billet clearance
            from probos.earned_agency import effective_recall_tier, resolve_billet_clearance, resolve_active_grants, RecallTier
            from probos.cognitive.episodic import resolve_recall_tier_params
            _rank = getattr(self, 'rank', None)
            _billet_clearance = resolve_billet_clearance(
                getattr(self, 'agent_type', ''),
                getattr(self._runtime, 'ontology', None),
            )
            # AD-622: Include active grants in tier resolution
            _active_grants = resolve_active_grants(
                getattr(self, 'sovereign_id', None) or self.id,
                getattr(self._runtime, 'clearance_grant_store', None),
            )
            _recall_tier = effective_recall_tier(_rank, _billet_clearance, _active_grants)
            _tier_cfg = getattr(mem_cfg, 'recall_tiers', None) if mem_cfg else None
            _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)

            # AD-568a: Classify retrieval strategy based on intent type
            from probos.cognitive.source_governance import (
                classify_retrieval_strategy, RetrievalStrategy,
                compute_adaptive_budget, compute_source_framing,
            )
            _intent_type = intent.intent if hasattr(intent, 'intent') else ""
            _episode_count = 0
            if hasattr(em, 'count_for_agent'):
                try:
                    _episode_count = await em.count_for_agent(_mem_id)
                except Exception:
                    _episode_count = 1  # Assume non-zero on error — fail toward retrieval
            # AD-568d: Thread confabulation rate from Counselor profile
            _confab_rate = 0.0
            try:
                if self._runtime and hasattr(self._runtime, 'registry'):
                    _counselor_agents = self._runtime.registry.get_by_pool("counselor")
                    if _counselor_agents:
                        _counselor = _counselor_agents[0]
                        if hasattr(_counselor, 'get_profile'):
                            _profile = _counselor.get_profile(self.id)
                            if _profile:
                                _confab_rate = getattr(_profile, 'confabulation_rate', 0.0)
            except Exception:
                logger.debug("AD-568d: Could not read confabulation rate, defaulting to 0.0")

            _retrieval_strategy = classify_retrieval_strategy(
                _intent_type,
                episodic_count=_episode_count,
                recent_confabulation_rate=_confab_rate,  # AD-568d
            )

            scored_results = []
            if _retrieval_strategy == RetrievalStrategy.NONE and not _ad604_results:
                # Skip episodic recall entirely — agent uses parametric + personality
                logger.debug("AD-568a: Skipping episodic recall for intent '%s' (strategy=NONE)", _intent_type)
                episodes = []
            else:
                # AD-568a DEEP: Expand parameters for deep retrieval
                if _retrieval_strategy == RetrievalStrategy.DEEP:
                    _tier_params = dict(_tier_params)  # Copy to avoid mutating shared config
                    _tier_params["k"] = int(_tier_params.get("k", 5) * 1.5)
                    _tier_params["context_budget"] = int(_tier_params.get("context_budget", 4000) * 1.5)
                    _tier_params["anchor_confidence_gate"] = max(
                        0.0, _tier_params.get("anchor_confidence_gate", 0.3) - 0.1
                    )
                    # AD-590: Relax composite floor for DEEP — wider net, quality still sorts
                    _tier_params["composite_score_floor"] = max(
                        0.0, _tier_params.get("composite_score_floor", 0.0) - 0.10
                    )
                    # AD-591: Relax quality budget for DEEP — allow more episodes and lower quality floor
                    _tier_params["max_recall_episodes"] = int(
                        _tier_params.get("max_recall_episodes", 0) * 1.5
                    ) if _tier_params.get("max_recall_episodes", 0) > 0 else 0
                    _tier_params["recall_quality_floor"] = max(
                        0.0, _tier_params.get("recall_quality_floor", 0.0) - 0.10
                    )

                if _ad604_results:
                    scored_results = _ad604_results
                elif hasattr(em, 'recall_weighted') and _tier_params.get("use_salience_weights", True):
                    _ad602_k = _tier_params.get("k", 5)
                    _ad602_weights = getattr(mem_cfg, 'recall_weights', None) if mem_cfg else None
                    if _ad602_strategy is not None:
                        if _ad602_strategy.recall_method == "weighted":
                            _ad602_k = _ad602_strategy.k
                        if _ad602_strategy.weights_override is not None:
                            observation["_ad602_weights_override"] = _ad602_strategy.weights_override
                            _base_weights = dict(_ad602_weights or {})
                            _base_weights.update(_ad602_strategy.weights_override)
                            _ad602_weights = _base_weights
                    scored_results = await em.recall_weighted(
                        _mem_id, query,
                        trust_network=trust_net,
                        hebbian_router=heb_router,
                        intent_type=intent.intent,
                        k=_ad602_k,
                        context_budget=_tier_params.get("context_budget", 4000),
                        weights=_ad602_weights,
                        anchor_confidence_gate=_tier_params.get("anchor_confidence_gate", 0.3),
                        composite_score_floor=_tier_params.get("composite_score_floor", 0.0),
                        max_recall_episodes=_tier_params.get("max_recall_episodes", 0),
                        recall_quality_floor=_tier_params.get("recall_quality_floor", 0.0),
                        convergence_bonus=getattr(mem_cfg, 'recall_convergence_bonus', 0.10) if mem_cfg else 0.10,
                        query_watch_section=_query_watch_section,  # BF-147: temporal match
                        temporal_match_weight=getattr(mem_cfg, 'recall_temporal_match_weight', 0.25) if mem_cfg else 0.25,
                        temporal_mismatch_penalty=getattr(mem_cfg, 'recall_temporal_mismatch_penalty', 0.15) if mem_cfg else 0.15,  # BF-155
                    )
                elif hasattr(em, 'recall_for_agent'):
                    # BASIC tier: vector similarity only, no salience weighting
                    episodes_raw = await em.recall_for_agent(
                        _mem_id, query, k=_tier_params.get("k", 3)
                    )
                    scored_results = []
                    if episodes_raw:
                        observation["_basic_recall_episodes"] = episodes_raw

                # AD-568b: Adaptive budget scaling based on retrieval quality
                if scored_results and _retrieval_strategy != RetrievalStrategy.NONE:
                    _budget_adj = compute_adaptive_budget(
                        _tier_params.get("context_budget", 4000),
                        recall_scores=scored_results,
                        episode_count=_episode_count,
                        strategy=_retrieval_strategy,
                    )
                    if _budget_adj.scale_factor != 1.0:
                        logger.debug(
                            "AD-568b: Budget adjusted %d→%d (%s)",
                            _budget_adj.original_budget, _budget_adj.adjusted_budget,
                            _budget_adj.reason,
                        )
                        # Re-apply budget enforcement with adjusted budget
                        _adjusted_episodes = []
                        _budget_used = 0
                        for rs in scored_results:
                            _ep_len = len(rs.episode.user_input) if hasattr(rs.episode, 'user_input') else 0
                            if _budget_used + _ep_len > _budget_adj.adjusted_budget and _adjusted_episodes:
                                break
                            _adjusted_episodes.append(rs)
                            _budget_used += _ep_len
                        scored_results = _adjusted_episodes

                # Fallback to old recall path if recall_weighted unavailable or returned nothing
                episodes = [rs.episode for rs in scored_results] if scored_results else []
                if not episodes:
                    episodes = observation.pop("_basic_recall_episodes", [])
                if not episodes:
                    episodes = await em.recall_for_agent(_mem_id, query, k=_tier_params.get("k", 3))
                if not episodes and hasattr(em, 'recent_for_agent'):
                    episodes = await em.recent_for_agent(_mem_id, k=_tier_params.get("k", 3))

                # AD-603: Merge anchor recall with semantic recall (score-aware)
                if _anchor_episodes:
                    from probos.types import RecallScore as _RecallScore

                    _is_scored = bool(_anchor_episodes and isinstance(_anchor_episodes[0], _RecallScore))
                    if _is_scored:
                        _seen_ids: set[str] = {rs.episode.id for rs in _anchor_episodes}
                        _merged: list[_RecallScore] = list(_anchor_episodes)
                        for rs in scored_results:
                            if rs.episode.id in _seen_ids:
                                continue
                            if (
                                _query_watch_section
                                and getattr(rs.episode, "anchors", None)
                                and getattr(rs.episode.anchors, "watch_section", "")
                                and rs.episode.anchors.watch_section != _query_watch_section
                            ):
                                logger.debug(
                                    "BF-155: Excluding episode %s (watch=%s) — query watch=%s",
                                    rs.episode.id[:8],
                                    rs.episode.anchors.watch_section,
                                    _query_watch_section,
                                )
                                continue
                            _merged.append(rs)
                            _seen_ids.add(rs.episode.id)
                        _merged.sort(key=lambda recall_score: recall_score.composite_score, reverse=True)
                        scored_results = _merged
                        episodes = [rs.episode for rs in scored_results]
                    else:
                        _seen_ids = {getattr(ep, 'id', id(ep)) for ep in _anchor_episodes}
                        for ep in episodes:
                            if getattr(ep, 'id', id(ep)) in _seen_ids:
                                continue
                            # BF-155: Exclude semantic episodes whose watch_section contradicts
                            # the query's temporal intent. Without this filter, wrong-watch
                            # episodes contaminate the anchor-filtered recall set.
                            if (
                                _query_watch_section
                                and getattr(ep, "anchors", None)
                                and getattr(ep.anchors, "watch_section", "")
                                and ep.anchors.watch_section != _query_watch_section
                            ):
                                logger.debug(
                                    "BF-155: Excluding episode %s (watch=%s) — query watch=%s",
                                    getattr(ep, 'id', '?')[:8],
                                    ep.anchors.watch_section,
                                    _query_watch_section,
                                )
                                continue
                            _anchor_episodes.append(ep)
                            _seen_ids.add(getattr(ep, 'id', id(ep)))
                        episodes = _anchor_episodes

                # AD-620: Oracle Service — clearance-based access
                # Agents with ORACLE tier (via rank or billet clearance) get Oracle on any strategy.
                if (
                    _recall_tier == RecallTier.ORACLE
                    and hasattr(self, '_runtime')
                    and hasattr(self._runtime, '_oracle_service')
                    and self._runtime._oracle_service
                ):
                    try:
                        oracle = self._runtime._oracle_service
                        oracle_text = await oracle.query_formatted(
                            query_text=query,
                            agent_id=_mem_id,
                            k_per_tier=3,
                            max_chars=2000,
                        )
                        if oracle_text:
                            observation["_oracle_context"] = oracle_text
                    except Exception:
                        logger.debug("AD-568a: Oracle query failed, continuing without")

            # AD-568c: Compute source priority framing
            _framing = None
            if scored_results:
                _scores = [getattr(rs, 'composite_score', 0.0) for rs in scored_results]
                _confs = [getattr(rs, 'anchor_confidence', 0.0) for rs in scored_results]
                _framing = compute_source_framing(
                    mean_anchor_confidence=sum(_confs) / len(_confs) if _confs else 0.0,
                    recall_count=len(scored_results),
                    mean_recall_score=sum(_scores) / len(_scores) if _scores else 0.0,
                    strategy=_retrieval_strategy,
                )
            elif _retrieval_strategy == RetrievalStrategy.NONE:
                _framing = compute_source_framing(strategy=RetrievalStrategy.NONE)
            observation["_source_framing"] = _framing

            # AD-568d: Compute source attribution snapshot
            _source_attribution = None
            try:
                from probos.cognitive.source_governance import compute_source_attribution
                _procedural_count = 0
                try:
                    if hasattr(self, '_procedure_store') and self._procedure_store:
                        _intent_procs = await self._procedure_store.get_by_intent(
                            _intent_type
                        ) if hasattr(self._procedure_store, 'get_by_intent') else []
                        _procedural_count = len(_intent_procs) if _intent_procs else 0
                except Exception:
                    pass
                _source_attribution = compute_source_attribution(
                    retrieval_strategy=_retrieval_strategy,
                    episodic_count=len(scored_results) if scored_results else 0,
                    procedural_count=_procedural_count,
                    oracle_used=bool(observation.get("_oracle_context")),
                    source_framing=_framing,
                    budget_adjustment=_budget_adj if '_budget_adj' in dir() else None,
                    confabulation_rate=_confab_rate,
                )
                observation["_source_attribution"] = _source_attribution
                observation["_source_attribution_obj"] = _source_attribution  # AD-568e: typed object for faithfulness checker
            except Exception:
                logger.debug("AD-568d: Source attribution computation failed")

            if episodes:
                # AD-502: Include relative timestamps on recalled memories
                rt = getattr(self, '_runtime', None)
                include_ts = True
                if rt and hasattr(rt, 'config') and hasattr(rt.config, 'temporal'):
                    include_ts = rt.config.temporal.include_episode_timestamps

                # AD-541: Verify episodes against EventLog at recall time
                event_log = getattr(self._runtime, 'event_log', None)

                memory_list = []
                for ep in episodes:
                    mem = {
                        "input": ep.user_input[:200] if ep.user_input else "",
                        "reflection": ep.reflection[:200] if ep.reflection else "",
                        "source": getattr(ep, 'source', 'direct'),
                    }
                    if include_ts and ep.timestamp > 0:
                        mem["age"] = format_duration(time.time() - ep.timestamp)

                    # AD-567b: Anchor context for formatting
                    anchors = getattr(ep, 'anchors', None)
                    if isinstance(anchors, AnchorFrame):
                        mem["anchor_channel"] = anchors.channel or ""
                        mem["anchor_department"] = anchors.department or ""
                        mem["anchor_participants"] = ", ".join(anchors.participants) if anchors.participants else ""
                        mem["anchor_trigger"] = anchors.trigger_type or ""

                    # AD-541 Pillar 1: Cross-check against EventLog
                    mem["verified"] = False
                    if event_log and ep.timestamp > 0 and ep.agent_ids:
                        try:
                            corroborating = await event_log.query(
                                agent_id=ep.agent_ids[0],
                                limit=1,
                            )
                            if corroborating:
                                for evt in corroborating:
                                    evt_ts = evt.get("timestamp", "")
                                    if evt_ts:
                                        from datetime import datetime
                                        try:
                                            evt_time = datetime.fromisoformat(evt_ts).timestamp()
                                            if abs(evt_time - ep.timestamp) < 120:
                                                mem["verified"] = True
                                                break
                                        except (ValueError, TypeError):
                                            pass
                        except Exception:
                            pass  # EventLog unavailable — leave unverified

                    memory_list.append(mem)

                observation["recent_memories"] = memory_list
        except Exception:
            logger.warning("BF-138: Failed to fetch episodic memory context — agent will respond without memory", exc_info=True)

        return observation

    def _build_episode_dag_summary(self, observation: dict) -> dict:
        """AD-568e: Build dag_summary with faithfulness + source attribution metadata."""
        summary: dict = {}
        # AD-568d: Source attribution
        _attr = observation.get("_source_attribution")
        if _attr is not None:
            try:
                if hasattr(_attr, 'primary_source'):
                    summary["source_attribution"] = {
                        "primary_source": _attr.primary_source.value if hasattr(_attr.primary_source, 'value') else str(_attr.primary_source),
                        "episodic_count": getattr(_attr, 'episodic_count', 0),
                        "procedural_count": getattr(_attr, 'procedural_count', 0),
                        "oracle_used": getattr(_attr, 'oracle_used', False),
                        "confabulation_rate": getattr(_attr, 'confabulation_rate', 0.0),
                    }
                elif isinstance(_attr, dict):
                    summary["source_attribution"] = _attr
            except Exception:
                pass
        # AD-568e: Faithfulness
        _faith = observation.get("_faithfulness")
        if _faith is not None:
            try:
                summary["faithfulness_score"] = _faith.score
                summary["faithfulness_grounded"] = _faith.grounded
            except Exception:
                pass
        # AD-589: Introspective faithfulness
        _intro_faith = observation.get("_introspective_faithfulness")
        if _intro_faith is not None:
            try:
                summary["introspective_faithfulness_score"] = _intro_faith.score
                summary["introspective_faithfulness_grounded"] = _intro_faith.grounded
                summary["introspective_contradictions"] = len(_intro_faith.contradictions)
            except Exception:
                pass
        return summary

    async def _try_anchor_recall(
        self, query: str, agent_mem_id: str
    ) -> tuple[list | None, str]:
        """AD-570c: Attempt anchor-indexed recall if query has relational signals.

        Returns (episodes, watch_section). BF-147: watch_section propagated
        for temporal match scoring in recall_weighted().
        """
        from probos.cognitive.source_governance import parse_anchor_query

        # Gather known callsigns for bare-name validation
        known_callsigns: list[str] = []
        if self._runtime and hasattr(self._runtime, 'callsign_registry'):
            try:
                _all = self._runtime.callsign_registry.all_callsigns()
                known_callsigns = list(_all.values()) if isinstance(_all, dict) else list(_all)
            except Exception:
                pass

        anchor = parse_anchor_query(query, known_callsigns=known_callsigns)
        if not anchor.has_anchor_signal:
            return None, ""

        em = self._runtime.episodic_memory
        if not hasattr(em, 'recall_by_anchor'):
            return None, anchor.watch_section or ""

        trust_net = getattr(self._runtime, 'trust_network', None)
        heb_router = getattr(self._runtime, 'hebbian_router', None)
        mem_cfg = None
        if hasattr(self._runtime, 'config') and hasattr(self._runtime.config, 'memory'):
            mem_cfg = self._runtime.config.memory

        if hasattr(em, 'recall_by_anchor_scored'):
            try:
                scored_results = await em.recall_by_anchor_scored(
                    department=anchor.department,
                    trigger_agent=anchor.trigger_agent,
                    participants=anchor.participants if anchor.participants else None,
                    time_range=anchor.time_range,
                    watch_section=anchor.watch_section,
                    semantic_query=anchor.semantic_query,
                    agent_id=agent_mem_id,
                    limit=10,
                    trust_network=trust_net,
                    hebbian_router=heb_router,
                    intent_type="",
                    weights=getattr(mem_cfg, 'recall_weights', None) if mem_cfg else None,
                    query_watch_section=anchor.watch_section or "",
                    temporal_match_weight=getattr(mem_cfg, 'recall_temporal_match_weight', 0.25) if mem_cfg else 0.25,
                    temporal_mismatch_penalty=getattr(mem_cfg, 'recall_temporal_mismatch_penalty', 0.15) if mem_cfg else 0.15,
                )
            except Exception:
                logger.debug("AD-603: recall_by_anchor_scored failed, falling back to unscored", exc_info=True)
                scored_results = None

            if scored_results:
                logger.debug(
                    "AD-603: Scored anchor recall returned %d results (dept=%s, agent=%s, watch=%s)",
                    len(scored_results), anchor.department, anchor.trigger_agent, anchor.watch_section,
                )
                return scored_results, anchor.watch_section or ""

        try:
            results = await em.recall_by_anchor(
                department=anchor.department,
                trigger_agent=anchor.trigger_agent,
                participants=anchor.participants if anchor.participants else None,
                time_range=anchor.time_range,
                watch_section=anchor.watch_section,  # BF-134
                semantic_query=anchor.semantic_query,
                agent_id=agent_mem_id,
                limit=10,
            )
        except Exception:
            logger.debug("AD-570c: recall_by_anchor failed", exc_info=True)
            return None, anchor.watch_section or ""

        if isinstance(results, list) and results:
            logger.debug(
                "AD-570c: Anchor recall returned %d episodes (dept=%s, agent=%s, watch=%s)",
                len(results), anchor.department, anchor.trigger_agent, anchor.watch_section,
            )
        return (results if isinstance(results, list) and results else None), anchor.watch_section or ""

    def _check_response_faithfulness(
        self,
        decision: dict,
        observation: dict,
    ) -> "FaithfulnessResult | None":
        """AD-568e: Post-decision faithfulness check.

        Compares the LLM response against recalled memories that were
        in the observation context. Fire-and-forget — never blocks the
        intent pipeline.

        Returns FaithfulnessResult or None if check cannot be performed.
        """
        try:
            from probos.cognitive.source_governance import (
                check_faithfulness as _check_faith,
                FaithfulnessResult,
            )

            # Extract response text from decision
            response_text = decision.get("llm_output", "") or decision.get("response", "")
            if not response_text:
                return None

            # Extract recalled memories from observation
            raw_memories = observation.get("memories", [])
            if not raw_memories:
                return FaithfulnessResult(
                    score=1.0,
                    evidence_overlap=0.0,
                    unsupported_claim_ratio=0.0,
                    evidence_count=0,
                    grounded=True,
                    detail="No episodic evidence to verify against — parametric response",
                )

            # Build memory text list
            memory_texts = []
            for mem in raw_memories:
                if isinstance(mem, dict):
                    text = mem.get("user_input", "") or mem.get("content", "")
                    if text:
                        memory_texts.append(text)
                elif isinstance(mem, str):
                    memory_texts.append(mem)

            # Get source attribution from observation (AD-568d)
            source_attr = observation.get("_source_attribution_obj")

            return _check_faith(
                response_text=response_text,
                recalled_memories=memory_texts,
                source_attribution=source_attr,
            )

        except Exception:
            logger.debug("AD-568e: Faithfulness check failed", exc_info=True)
            return None

    def _check_introspective_faithfulness(
        self,
        decision: dict,
    ) -> "IntrospectiveFaithfulnessResult | None":
        """AD-589: Post-decision introspective faithfulness check.

        Compares the LLM response against the CognitiveArchitectureManifest
        (AD-587) and available telemetry. Fire-and-forget — never blocks
        the intent pipeline. Follows AD-568e pattern exactly.
        """
        try:
            from probos.cognitive.source_governance import (
                check_introspective_faithfulness as _check_intro,
                IntrospectiveFaithfulnessResult,
            )

            response_text = decision.get("llm_output", "") or decision.get("response", "")
            if not response_text:
                return None

            # AD-587: Manifest is static architectural truth — construct directly
            from probos.cognitive.orientation import CognitiveArchitectureManifest
            manifest = CognitiveArchitectureManifest()

            # Get telemetry snapshot if available (AD-588) — use cached snapshot
            # from last DM/WR injection to avoid async call in sync method
            telemetry = None
            _wm = getattr(self, '_working_memory', None)
            if _wm:
                telemetry = getattr(_wm, '_last_telemetry_snapshot', None)

            return _check_intro(
                response_text=response_text,
                manifest=manifest,
                telemetry_snapshot=telemetry,
            )
        except Exception:
            logger.debug("AD-589: introspective faithfulness check failed", exc_info=True)
            return None

    async def _store_action_episode(self, intent: IntentMessage, observation: dict, report: dict) -> None:
        """AD-430c: Universal post-action episode storage for crew agents.

        This is the safety net — ensures every crew agent action produces a memory
        record. Callers that already store episodes (proactive loop, Ward Room
        service, HXI API) produce sovereign-shard episodes through their own paths,
        but this hook captures any actions that would otherwise be missed.

        Deduplication: proactive_think is skipped (AD-430a stores in proactive.py).
        ward_room_notification is skipped (AD-430a stores in ward_room.py).
        direct_message from hxi_profile is skipped (AD-430b stores in api.py).
        direct_message from captain (shell /hail) is skipped (shell.py stores).
        """
        # AD-566a: Skip episode storage for qualification test interactions
        if intent.params.get("_qualification_test"):
            return

        # Skip intents that already have dedicated episode storage
        if intent.intent == "proactive_think":
            return
        if intent.intent == "ward_room_notification":
            return

        params = observation.get("params", {})
        source = params.get("from", "")
        if intent.intent == "direct_message" and source in ("hxi_profile", "captain"):
            return

        # Guard: need runtime + episodic memory + crew check
        if not self._runtime:
            return
        if not hasattr(self._runtime, 'episodic_memory') or not self._runtime.episodic_memory:
            return
        if not hasattr(self._runtime, 'ontology'):
            return
        from probos.crew_utils import is_crew_agent as _is_crew
        if not _is_crew(self, getattr(self._runtime, 'ontology', None)):
            return

        try:
            import time as _time
            from probos.types import AnchorFrame, Episode, MemorySource

            result_text = str(report.get("result", ""))[:500]
            callsign = ""
            if hasattr(self._runtime, 'callsign_registry'):
                callsign = self._runtime.callsign_registry.get_callsign(self.agent_type) or ""

            query_text = params.get("text", intent.context or intent.intent)

            # AD-567a: Resolve department for anchor
            _dept = ""
            try:
                _ont = getattr(self._runtime, 'ontology', None)
                if _ont:
                    _dept = _ont.get_agent_department(self.agent_type) or ""
                if not _dept:
                    from probos.cognitive.standing_orders import get_department as _get_dept
                    _dept = _get_dept(self.agent_type) or ""
            except Exception:
                pass

            # AD-567b: SECONDHAND source wiring
            # If this action was triggered by another agent's communication,
            # tag the resulting episode as secondhand.
            _source = MemorySource.DIRECT
            _trigger_from = params.get("from", "")
            if _trigger_from and intent.intent not in ("direct_message",):
                # Check if trigger agent is someone else
                _my_ids = {
                    getattr(self, 'sovereign_id', None) or self.id,
                    self.agent_type,
                    callsign,
                    self.id,
                }
                _my_ids.discard("")
                _my_ids.discard(None)
                if _trigger_from not in _my_ids:
                    _source = MemorySource.SECONDHAND

            episode = Episode(
                user_input=f"[Action: {intent.intent}] {callsign or self.agent_type}: {str(query_text)[:200]}",
                timestamp=_time.time(),
                agent_ids=[getattr(self, 'sovereign_id', None) or self.id],
                outcomes=[{
                    "intent": intent.intent,
                    "success": report.get("success", False),
                    "response": result_text,
                    "agent_type": self.agent_type,
                    "source": source or "intent_bus",
                    # AD-632g: Chain metadata for procedure extraction
                    **(observation.get("_chain_metadata") or {}),
                    # AD-643b: Trigger learning feedback
                    **({
                        "undeclared_actions": observation["_undeclared_action_feedback"].get("undeclared_actions", []),
                        "missed_skills": observation["_undeclared_action_feedback"].get("missed_skills", []),
                    } if observation.get("_undeclared_action_feedback") else {}),
                }],
                dag_summary=self._build_episode_dag_summary(observation),  # AD-568e
                reflection=f"{callsign or self.agent_type} handled {intent.intent}: {result_text[:100]}",
                source=_source,
                anchors=AnchorFrame(
                    channel="action",
                    department=_dept,
                    trigger_type=intent.intent,
                    trigger_agent=params.get("from", ""),
                    # AD-663: Provenance - the triggering observation is the root artifact
                    source_origin_id=observation.get("correlation_id", "") or "",
                    artifact_version=hashlib.sha256(
                        str(query_text)[:500].encode("utf-8")
                    ).hexdigest()[:16],
                ),
                correlation_id=observation.get("correlation_id", ""),
            )
            from probos.cognitive.episodic import EpisodicMemory
            if EpisodicMemory.should_store(episode):
                await self._runtime.episodic_memory.store(episode)
        except Exception:
            logger.debug("Failed to store action episode", exc_info=True)

    def _resolve_tier(self) -> str:
        """Determine which LLM tier to use.  Default: 'standard'.
        Override in subclasses for tier-specific routing."""
        return "standard"

    # --- Decision cache helpers (AD-272) ---

    def _compute_cache_key(self, observation: dict) -> str:
        """Compute a deterministic hash from instructions + observation."""
        obs_str = json.dumps(observation, sort_keys=True, default=str)
        key_material = f"{self.instructions}|{obs_str}"
        return hashlib.sha256(key_material.encode()).hexdigest()[:16]

    def _get_cache_ttl(self) -> float:
        """Determine TTL based on agent instructions."""
        if not self.instructions:
            return self._cache_ttl_seconds
        lower = self.instructions.lower()
        if any(kw in lower for kw in ("real-time", "current", "live", "latest", "now", "price", "weather", "stock")):
            return 120.0  # 2 minutes
        if any(kw in lower for kw in ("translate", "define", "calculate", "convert", "summarize")):
            return 3600.0  # 1 hour
        return self._cache_ttl_seconds

    @classmethod
    def evict_cache_for_type(cls, agent_type: str, observation: dict | None = None) -> int:
        """Evict cache entries for an agent type. Returns count of evicted entries."""
        cache = _DECISION_CACHES.get(agent_type, {})
        if not cache:
            return 0
        if observation is None:
            count = len(cache)
            cache.clear()
            return count
        return 0

    @classmethod
    def cache_stats(cls) -> dict[str, dict[str, int]]:
        """Return cache statistics per agent type."""
        stats = {}
        for agent_type, cache in _DECISION_CACHES.items():
            stats[agent_type] = {
                "entries": len(cache),
                "hits": _CACHE_HITS.get(agent_type, 0),
                "misses": _CACHE_MISSES.get(agent_type, 0),
            }
        return stats
