"""NL-to-Graph Query agent (AD-691) — wraps NLGraphQueryService.

Declares an ``nl_graph_query`` IntentDescriptor so the decomposer
(``cognitive/decomposer.py``) — which discovers intents dynamically from
registered agents — routes structural-query natural language
("who reports to chief_engineer?", "what depends on the dream pipeline?",
"how is medbay connected to security?") to this agent.

The agent is purely a thin dispatcher onto ``runtime.nl_graph_query`` and
holds no state of its own. NEVER raises into the caller — every failure
path returns a well-formed degraded ``IntentResult``.
"""

from __future__ import annotations

import logging
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)


class NLGraphQueryAgent(BaseAgent):
    """Decomposer-routable surface for ``runtime.nl_graph_query``.

    Examples of routed natural-language queries:
      - "who reports to chief_engineer?"
      - "what depends on the dream pipeline?"
      - "how is medbay connected to security?"
    """

    agent_type: str = "nl_graph_query"
    tier = "utility"
    default_capabilities = [
        CapabilityDescriptor(
            can="nl_graph_query",
            detail=(
                "Translate natural-language structural questions into typed "
                "graph traversals over the knowledge edge store and return a "
                "synthesized answer with explicit graph-edge provenance."
            ),
        ),
    ]
    initial_confidence: float = 0.85
    intent_descriptors = [
        IntentDescriptor(
            name="nl_graph_query",
            params={
                "query": (
                    "natural-language question about relationships between "
                    "entities (agents, departments, duties, incidents, "
                    "decisions, findings, capabilities, standing_orders)"
                ),
                "max_hops": "optional traversal depth (1-3, default 2)",
                "limit": "optional max edges returned (default 10)",
            },
            description=(
                "Answer structural / relationship questions over the "
                "knowledge graph. Use for queries about who reports to whom, "
                "what depends on what, how two entities are connected, or "
                "which entities share a relation. Returns a natural-language "
                "answer with [graph: <edge.id>] provenance."
            ),
            requires_consensus=False,
            requires_reflect=True,
            tier="utility",
        ),
    ]

    _handled_intents = {"nl_graph_query"}

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive → decide → act → report."""
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None

        plan = await self.decide(observation)
        if plan is None:
            return None

        result = await self.act(plan)
        report = await self.report(result)

        success = bool(report.get("success", False))
        self.update_confidence(success)

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("data"),
            error=report.get("error"),
            confidence=self.confidence,
        )

    async def perceive(self, intent: dict[str, Any]) -> Any:
        if intent.get("intent") not in self._handled_intents:
            return None
        return {"params": intent.get("params", {}) or {}}

    async def decide(self, observation: Any) -> Any:
        params = observation["params"]
        nl = params.get("query") or params.get("q") or params.get("text") or ""
        if not isinstance(nl, str) or not nl.strip():
            return None
        return {
            "query": nl.strip(),
            "max_hops": params.get("max_hops"),
            "limit": params.get("limit"),
        }

    async def act(self, plan: Any) -> Any:
        rt = self._runtime
        if rt is None:
            return {"success": False, "error": "No runtime reference available"}
        service = getattr(rt, "nl_graph_query", None)
        if service is None:
            return {"success": False, "error": "nl_graph_query service unavailable"}
        try:
            result = await service.query(
                plan["query"],
                max_hops=plan.get("max_hops"),
                limit=plan.get("limit"),
            )
        except Exception as e:  # Tier-2: log-and-degrade
            logger.warning(
                "AD-691: NLGraphQueryAgent.act delegation failed", exc_info=True,
            )
            return {"success": False, "error": f"nl_graph_query failed: {e}"}
        return {
            "success": True,
            "data": {
                "query": result.query,
                "answer": result.answer,
                "provenance": list(result.provenance),
                "extracted_entities": [e.to_dict() for e in result.extracted_entities],
                "edge_count": len(result.edges_traversed),
                "path_count": len(result.paths),
            },
        }

    async def report(self, result: Any) -> dict[str, Any]:
        return result
