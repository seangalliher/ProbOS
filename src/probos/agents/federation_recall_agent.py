"""AD-479d: FederationRecallAgent — federated episodic recall.

Registers the ``recall_federated`` IntentDescriptor (read-only, no
consensus). The handler queries the local ``EpisodicMemory.recall(query, k)``
and returns the top-k episodes. Federation fan-out happens via the existing
``FederationBridge.forward_intent`` wired into ``IntentBus._federation_fn``;
each peer's local ``FederationRecallAgent`` runs its own local recall and
returns episodes back to the originator, which deduplicates by
``episode_id`` keeping the highest-score result per id.
"""

from __future__ import annotations

import logging
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import IntentDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)


class FederationRecallAgent(BaseAgent):
    """Federated recall agent — aggregates ``recall(query, k)`` across peers."""

    agent_type = "federation_recall"
    tier = "utility"
    intent_descriptors: list[IntentDescriptor] = [
        IntentDescriptor(
            name="recall_federated",
            description="Recall episodic memories across federated peer ships.",
            tier="utility",
            requires_consensus=False,
        ),
    ]

    def __init__(self, pool: str = "default", **kwargs: Any) -> None:
        super().__init__(pool=pool, **kwargs)

    async def perceive(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Extract query + k from the intent params."""
        if isinstance(intent, IntentMessage):
            params = intent.params
            intent_name = intent.intent
        elif isinstance(intent, dict):
            params = intent.get("params", {}) or {}
            intent_name = intent.get("intent", "")
        else:
            params = {}
            intent_name = ""
        if intent_name != "recall_federated":
            return {"_skip": True, "intent_id": getattr(intent, "id", "")}
        return {
            "query": str(params.get("query", "")),
            "k": int(params.get("k", 5)),
            "intent_id": getattr(intent, "id", ""),
        }

    async def decide(self, observation: dict[str, Any]) -> dict[str, Any]:
        """Pass through — perceive already produced the decision shape."""
        return observation

    async def act(self, plan: dict[str, Any]) -> IntentResult:
        """Run local recall and return a merged top-k result."""
        intent_id = plan.get("intent_id", "") or "recall_federated"
        if plan.get("_skip"):
            return IntentResult(
                intent_id=intent_id,
                agent_id=self.id,
                success=False,
                result=None,
                error="not recall_federated",
                confidence=0.0,
            )
        query = plan["query"]
        k = plan["k"]

        runtime = self._runtime
        local_results: list[dict[str, Any]] = []
        ep = getattr(runtime, "episodic_memory", None) if runtime is not None else None
        node_id = ""
        if runtime is not None:
            try:
                node_id = runtime.config.federation.node_id
            except AttributeError:
                node_id = ""
        if ep is not None:
            try:
                episodes = await ep.recall(query, k=k)
            except Exception as exc:
                logger.warning(
                    "Federated recall: local recall failed for query=%r: %s",
                    query, exc,
                )
                episodes = []
            for e in episodes:
                local_results.append({
                    "episode_id": getattr(e, "episode_id", None),
                    "summary": getattr(e, "summary", None),
                    "score": float(getattr(e, "score", 0.0)),
                    "source_node": node_id,
                })

        # Deduplicate by episode_id while preserving best score per id.
        seen: dict[str, dict[str, Any]] = {}
        for record in local_results:
            ep_id = record.get("episode_id")
            if ep_id is None:
                continue
            if ep_id not in seen or float(record["score"]) > float(seen[ep_id]["score"]):
                seen[ep_id] = record

        merged = sorted(seen.values(), key=lambda r: -float(r["score"]))[:k]
        return IntentResult(
            intent_id=intent_id,
            agent_id=self.id,
            success=True,
            result={"episodes": merged, "count": len(merged)},
            error=None,
            confidence=0.6,
        )

    async def report(self, result: IntentResult) -> dict[str, Any]:
        """Pass through — IntentResult already shaped for the bus."""
        return {
            "intent_id": result.intent_id,
            "agent_id": result.agent_id,
            "success": result.success,
            "result": result.result,
            "error": result.error,
            "confidence": result.confidence,
        }
