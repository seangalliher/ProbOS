"""CognitiveAgent — agent whose decide() step consults an LLM guided by instructions."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, ClassVar

from probos.events import EventType
from probos.substrate.agent import BaseAgent
from probos.types import AnchorFrame, IntentMessage, IntentResult, LLMRequest, Skill
from probos.utils import format_duration

logger = logging.getLogger(__name__)

# Module-level decision cache keyed by agent_type (AD-272)
_DECISION_CACHES: dict[str, dict[str, tuple[dict, float, float]]] = {}
# {agent_type: {hash: (decision_dict, created_at_monotonic, ttl_seconds)}}
_CACHE_HITS: dict[str, int] = {}
_CACHE_MISSES: dict[str, int] = {}


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

        # AD-573: Unified working memory — cognitive continuity across pathways
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        self._working_memory = AgentWorkingMemory()

        # Validate instructions exist
        if not self.instructions:
            raise ValueError(
                f"{self.__class__.__name__} requires non-empty instructions"
            )

    def set_strategy_advisor(self, advisor) -> None:
        """Attach a StrategyAdvisor for cross-agent knowledge transfer (AD-384)."""
        self._strategy_advisor = advisor

    def set_orientation(self, rendered: str, context: Any = None) -> None:
        """AD-567g / BF-113: Set orientation text and context (public setter for LoD)."""
        self._orientation_rendered = rendered
        self._orientation_context = context

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
            trust_score = _rt.trust_network.get_trust(agent_type)
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
        """Package the intent as an observation for the LLM."""
        if isinstance(intent, IntentMessage):
            return {
                "intent": intent.intent,
                "params": intent.params,
                "context": intent.context,
                "intent_id": intent.id,  # AD-432: Preserve for journal traceability
            }
        # Dict fallback (for compatibility with BaseAgent contract)
        return {
            "intent": intent.get("intent", "unknown") if isinstance(intent, dict) else "unknown",
            "params": intent.get("params", {}) if isinstance(intent, dict) else {},
            "context": intent.get("context", "") if isinstance(intent, dict) else "",
        }

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
                        )
                    except Exception:
                        logger.debug("Journal recording failed", exc_info=True)
                return {**decision, "cached": True}
            else:
                del cache[cache_key]

        _CACHE_MISSES[self.agent_type] = _CACHE_MISSES.get(self.agent_type, 0) + 1

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
                    )
                except Exception:
                    logger.debug("Journal recording failed", exc_info=True)
            return procedural_result

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

        if is_conversation:
            # For 1:1 and ward room, use personality + standing orders only.
            # Exclude domain-specific task instructions (report formats, output blocks)
            # so the LLM responds naturally as itself.
            composed = compose_instructions(
                agent_type=getattr(self, "agent_type", self.__class__.__name__.lower()),
                hardcoded_instructions="",
                callsign=self._resolve_callsign(),
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
            )

        request = LLMRequest(
            prompt=user_message,
            system_prompt=composed,
            tier=self._resolve_tier(),
        )

        # AD-431: Time the LLM call for journal
        _t0 = time.monotonic()
        response = await self._llm_client.complete(request)
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

        # Fast path: self-deselect for unrecognized intents before any LLM call
        if not is_direct and intent.intent not in self._handled_intents:
            return None

        # AD-534c: compound step replay — zero-token, bypass full cognitive lifecycle
        if intent.intent == "compound_step_replay" and intent.target_agent_id == self.id:
            return await self._handle_compound_step_replay(intent)

        # Skill dispatch — direct handler call, no LLM reasoning
        if intent.intent in self._skills:
            skill = self._skills[intent.intent]
            return await skill.handler(intent, llm_client=self._llm_client)

        # Cognitive lifecycle — LLM-guided reasoning
        observation = await self.perceive(intent)

        # AD-430c (Pillar 4): Enrich observation with relevant episodic memories
        observation = await self._recall_relevant_memories(intent, observation)

        decision = await self.decide(observation)
        decision["intent"] = intent.intent  # AD-398: propagate intent name to act()

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
                if _rt and hasattr(_rt, '_emit_event'):
                    try:
                        _rt._emit_event(EventType.SELF_MODEL_DRIFT, {
                            "agent_id": self.id,
                            "callsign": self.callsign or self.agent_type,
                            "score": _intro_faith.score,
                            "contradictions": _intro_faith.contradictions[:3],
                            "claims_detected": _intro_faith.claims_detected,
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
                if _rt and hasattr(_rt, '_emit_event'):
                    try:
                        _rt._emit_event(EventType.TASK_EXECUTION_COMPLETE, {
                            "agent_id": self.id,
                            "agent_type": getattr(self, 'agent_type', ''),
                            "intent_type": intent.intent,
                            "success": True,
                            "used_procedure": True,
                            "compound_dispatched": True,
                            "steps_dispatched": compound_result.get("steps_dispatched", 0),
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

        # AD-430c (Pillar 5): Store action as episodic memory for crew agents
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
        if _rt and hasattr(_rt, '_emit_event'):
            try:
                _rt._emit_event(EventType.TASK_EXECUTION_COMPLETE, {
                    "agent_id": self.id,
                    "agent_type": getattr(self, 'agent_type', ''),
                    "intent_type": intent.intent,
                    "success": success,
                    "used_procedure": decision.get("cached", False),
                })
            except Exception:
                pass  # Fire-and-forget, never block the intent pipeline

        # AD-534b: Emit fallback learning event for dream-time processing
        if success and self._last_fallback_info is not None:
            if _rt and hasattr(_rt, '_emit_event'):
                try:
                    from probos.config import MAX_FALLBACK_RESPONSE_CHARS
                    _llm_output = ""
                    if llm_decision is not None:
                        _llm_output = llm_decision.get("llm_output", "")
                    else:
                        _llm_output = decision.get("llm_output", "")
                    _rt._emit_event(EventType.PROCEDURE_FALLBACK_LEARNING, {
                        "agent_id": self.id,
                        "intent_type": intent.intent,
                        "fallback_type": self._last_fallback_info["type"],
                        "procedure_id": self._last_fallback_info["procedure_id"],
                        "procedure_name": self._last_fallback_info.get("procedure_name", ""),
                        "near_miss_score": self._last_fallback_info.get("score", 0.0),
                        "rejection_reason": self._last_fallback_info.get("reason", ""),
                        "llm_response": _llm_output[:MAX_FALLBACK_RESPONSE_CHARS],
                        "timestamp": time.time(),
                    })
                except Exception:
                    pass  # Fire-and-forget
            self._last_fallback_info = None  # Consumed

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("result"),
            error=report.get("error"),
            confidence=self.confidence,
        )

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
            return f"Responded in Ward Room #{channel}: '{output[:100]}'"
        if intent_type == "proactive_think":
            if "[NO_RESPONSE]" in output:
                return ""  # Don't record silence
            return f"Proactive observation: '{output[:150]}'"
        return f"Handled {intent_type}: '{output[:100]}'"

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
        Override in subclasses for custom formatting."""
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
                parts.append(f"[COGNITIVE ZONE: {_zone.upper()}]")
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
                    f"[Source awareness: Your response draws on: {', '.join(_sources_present)}. "
                    f"Primary basis: {_attr.primary_source.value}.]"
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
                wr_parts.append(f"[COGNITIVE ZONE: {_zone.upper()}]")

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
                    f"[Source awareness: Your response draws on: {', '.join(_sources_present)}. "
                    f"Primary basis: {_attr.primary_source.value}.]"
                )

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
                    pt_parts.append(f"[COGNITIVE ZONE: {zone.upper()}]")
                    if zone_note:
                        pt_parts.append(zone_note)
                    pt_parts.append("")

                pt_parts.append("--- Your Recent Activity (self-monitoring) ---")

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
                    pt_parts.append(f"--- Notebook: {nb_content['topic']} ---")
                    pt_parts.append(nb_content["snippet"])
                    pt_parts.append("--- End Notebook ---")

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

            # AD-462c: Resolve recall tier from agent rank
            from probos.earned_agency import recall_tier_from_rank, RecallTier
            from probos.cognitive.episodic import resolve_recall_tier_params
            _rank = getattr(self, 'rank', None)
            _recall_tier = recall_tier_from_rank(_rank) if _rank else RecallTier.ENHANCED
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
            if _retrieval_strategy == RetrievalStrategy.NONE:
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

                if hasattr(em, 'recall_weighted') and _tier_params.get("use_salience_weights", True):
                    scored_results = await em.recall_weighted(
                        _mem_id, query,
                        trust_network=trust_net,
                        hebbian_router=heb_router,
                        intent_type=intent.intent,
                        k=_tier_params.get("k", 5),
                        context_budget=_tier_params.get("context_budget", 4000),
                        weights=getattr(mem_cfg, 'recall_weights', None) if mem_cfg else None,
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

                # AD-570c: Merge anchor recall with semantic recall
                if _anchor_episodes:
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

                # AD-568a: Oracle Service for ORACLE-tier agents with DEEP strategy
                if (
                    _recall_tier == RecallTier.ORACLE
                    and _retrieval_strategy == RetrievalStrategy.DEEP
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
                }],
                dag_summary=self._build_episode_dag_summary(observation),  # AD-568e
                reflection=f"{callsign or self.agent_type} handled {intent.intent}: {result_text[:100]}",
                source=_source,
                anchors=AnchorFrame(
                    channel="action",
                    department=_dept,
                    trigger_type=intent.intent,
                    trigger_agent=params.get("from", ""),
                ),
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
