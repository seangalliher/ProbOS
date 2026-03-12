"""CognitiveAgent — agent whose decide() step consults an LLM guided by instructions."""

from __future__ import annotations

import logging
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import IntentMessage, IntentResult, LLMRequest, Skill

logger = logging.getLogger(__name__)


class CognitiveAgent(BaseAgent):
    """Agent whose decide() step consults an LLM guided by instructions.

    The perceive/decide/act/report lifecycle is preserved.  ``decide()``
    invokes the LLM with ``instructions`` as the system prompt and the
    current observation (from ``perceive()``) as the user message.
    ``act()`` executes based on the LLM's decision — subclasses override
    it for structured output parsing.
    """

    tier = "domain"  # Cognitive agents are domain-tier by default

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

        # Validate instructions exist
        if not self.instructions:
            raise ValueError(
                f"{self.__class__.__name__} requires non-empty instructions"
            )

    async def perceive(self, intent: Any) -> dict:
        """Package the intent as an observation for the LLM."""
        if isinstance(intent, IntentMessage):
            return {
                "intent": intent.intent,
                "params": intent.params,
                "context": intent.context,
            }
        # Dict fallback (for compatibility with BaseAgent contract)
        return {
            "intent": intent.get("intent", "unknown") if isinstance(intent, dict) else "unknown",
            "params": intent.get("params", {}) if isinstance(intent, dict) else {},
            "context": intent.get("context", "") if isinstance(intent, dict) else "",
        }

    async def decide(self, observation: dict) -> dict:
        """Consult the LLM with instructions + observation."""
        if not self._llm_client:
            return {"action": "error", "reason": "No LLM client available"}

        # Build user message from observation
        user_message = self._build_user_message(observation)

        request = LLMRequest(
            prompt=user_message,
            system_prompt=self.instructions,
            tier=self._resolve_tier(),
        )
        response = await self._llm_client.complete(request)

        return {
            "action": "execute",
            "llm_output": response.content,
            "tier_used": response.tier,
        }

    async def act(self, decision: dict) -> dict:
        """Execute based on LLM decision.  Override for structured output."""
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}
        return {
            "success": True,
            "result": decision.get("llm_output", ""),
        }

    async def report(self, result: dict) -> dict:
        """Package result as a dict (compatible with BaseAgent contract)."""
        return result

    async def handle_intent(self, intent: IntentMessage) -> IntentResult:
        """Skills first, then cognitive lifecycle."""
        # Skill dispatch — direct handler call, no LLM reasoning
        if intent.intent in self._skills:
            skill = self._skills[intent.intent]
            return await skill.handler(intent, llm_client=self._llm_client)

        # Cognitive lifecycle — LLM-guided reasoning
        observation = await self.perceive(intent)
        decision = await self.decide(observation)
        result = await self.act(decision)
        report = await self.report(result)

        success = report.get("success", False)
        self.update_confidence(success)

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

    def _build_user_message(self, observation: dict) -> str:
        """Build the user message from the observation dict.
        Override in subclasses for custom formatting."""
        parts = [f"Intent: {observation.get('intent', 'unknown')}"]
        if observation.get("params"):
            parts.append(f"Parameters: {observation['params']}")
        if observation.get("context"):
            parts.append(f"Context: {observation['context']}")
        if observation.get("fetched_content"):
            parts.append(f"Fetched content:\n{observation['fetched_content']}")
        return "\n".join(parts)

    def _resolve_tier(self) -> str:
        """Determine which LLM tier to use.  Default: 'standard'.
        Override in subclasses for tier-specific routing."""
        return "standard"
