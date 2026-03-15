"""CognitiveAgent — agent whose decide() step consults an LLM guided by instructions."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import IntentMessage, IntentResult, LLMRequest, Skill

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
                return {**decision, "cached": True}
            else:
                del cache[cache_key]

        _CACHE_MISSES[self.agent_type] = _CACHE_MISSES.get(self.agent_type, 0) + 1

        # --- LLM call (cache miss) ---
        user_message = self._build_user_message(observation)

        request = LLMRequest(
            prompt=user_message,
            system_prompt=self.instructions,
            tier=self._resolve_tier(),
        )
        response = await self._llm_client.complete(request)

        decision = {
            "action": "execute",
            "llm_output": response.content,
            "tier_used": response.tier,
        }

        # --- Store in cache ---
        ttl = self._get_cache_ttl()
        cache[cache_key] = (decision, time.monotonic(), ttl)

        # Evict oldest entry if cache exceeds 1000 per agent type
        if len(cache) > 1000:
            oldest_key = min(cache, key=lambda k: cache[k][1])
            del cache[oldest_key]

        return decision

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

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Skills first, then cognitive lifecycle.

        Returns None (self-deselect) for intents not in _handled_intents.
        """
        # Fast path: self-deselect for unrecognized intents before any LLM call
        if intent.intent not in self._handled_intents:
            return None

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
