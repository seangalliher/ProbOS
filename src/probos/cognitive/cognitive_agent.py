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

        # Strategy advisor (AD-384) — optional cross-agent knowledge transfer
        self._strategy_advisor = None

        # Validate instructions exist
        if not self.instructions:
            raise ValueError(
                f"{self.__class__.__name__} requires non-empty instructions"
            )

    def set_strategy_advisor(self, advisor) -> None:
        """Attach a StrategyAdvisor for cross-agent knowledge transfer (AD-384)."""
        self._strategy_advisor = advisor

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
                )
            elif observation.get("intent") == "proactive_think":
                composed += (
                    "\n\nYou are reviewing recent ship activity during a quiet moment. "
                    "If you notice something noteworthy — a pattern, a concern, an insight "
                    "related to your expertise — compose a brief observation (2-4 sentences). "
                    "This will be posted to the Ward Room as a new thread. "
                    "Speak in your natural voice. Be specific and actionable. "
                    "If nothing warrants attention right now, respond with exactly: [NO_RESPONSE]"
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
        else:
            composed = compose_instructions(
                agent_type=getattr(self, "agent_type", self.__class__.__name__.lower()),
                hardcoded_instructions=self.instructions or "",
            )

        request = LLMRequest(
            prompt=user_message,
            system_prompt=composed,
            tier=self._resolve_tier(),
        )
        response = await self._llm_client.complete(request)

        decision = {
            "action": "execute",
            "llm_output": response.content,
            "tier_used": response.tier,
        }

        # Record strategy outcomes (AD-384)
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
            intent.intent in ("direct_message", "ward_room_notification", "proactive_think")
            and intent.target_agent_id == self.id
        )

        # Fast path: self-deselect for unrecognized intents before any LLM call
        if not is_direct and intent.intent not in self._handled_intents:
            return None

        # Skill dispatch — direct handler call, no LLM reasoning
        if intent.intent in self._skills:
            skill = self._skills[intent.intent]
            return await skill.handler(intent, llm_client=self._llm_client)

        # Cognitive lifecycle — LLM-guided reasoning
        observation = await self.perceive(intent)
        decision = await self.decide(observation)
        decision["intent"] = intent.intent  # AD-398: propagate intent name to act()
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
        intent_name = observation.get("intent", "unknown")
        params = observation.get("params", {})

        # AD-397: direct_message — conversational context for 1:1 sessions
        if intent_name == "direct_message":
            parts: list[str] = []
            session_history = params.get("session_history", [])
            if session_history:
                parts.append("Previous conversation:")
                for entry in session_history:
                    role = entry.get("role", "unknown")
                    text = entry.get("text", "")
                    parts.append(f"  {role}: {text}")
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
            if context:
                wr_parts.append(f"\nConversation so far:\n{context}")
            # AD-407d: Distinguish Captain vs crew member posts
            author_id = params.get("author_id", "")
            if author_id == "captain":
                wr_parts.append(f"\nThe Captain posted the above.")
            else:
                wr_parts.append(f"\n{author_callsign} posted the above.")
            wr_parts.append("Respond naturally as yourself. Share your perspective if you have something meaningful to contribute.")
            wr_parts.append("If this topic is outside your expertise or you have nothing to add, respond with exactly: [NO_RESPONSE]")
            return "\n".join(wr_parts)

        # Phase 28b: proactive_think — idle review cycle
        if intent_name == "proactive_think":
            context_parts = params.get("context_parts", {})
            trust_score = params.get("trust_score", 0.5)
            agency_level = params.get("agency_level", "suggestive")

            pt_parts: list[str] = []
            pt_parts.append("[Proactive Review Cycle]")
            pt_parts.append(f"Your trust: {trust_score} | Agency: {agency_level}")
            pt_parts.append("")

            # Recent memories
            memories = context_parts.get("recent_memories", [])
            if memories:
                pt_parts.append("Recent memories (your experiences):")
                for m in memories:
                    if m.get("reflection"):
                        pt_parts.append(f"  - {m['reflection']}")
                    elif m.get("input"):
                        pt_parts.append(f"  - Handled: {m['input']}")
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

            pt_parts.append("Based on this review, decide if anything warrants an observation or insight.")
            pt_parts.append("If something is noteworthy, compose a brief Ward Room post (2-4 sentences).")
            pt_parts.append("If nothing warrants attention, respond with exactly: [NO_RESPONSE]")
            return "\n".join(pt_parts)

        parts = [f"Intent: {intent_name}"]
        if params:
            parts.append(f"Parameters: {params}")
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
