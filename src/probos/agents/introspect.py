"""Introspection agent — self-referential queries about ProbOS state."""

from __future__ import annotations

import logging
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)


class IntrospectionAgent(BaseAgent):
    """Agent that answers queries about ProbOS's own state.

    Reads from runtime internals (registry, trust, Hebbian weights,
    episodic memory, attention, workflow cache) and returns structured
    information.  Purely observational — never mutates runtime state.
    """

    agent_type: str = "introspect"
    tier = "utility"
    default_capabilities = [
        CapabilityDescriptor(
            can="introspect",
            detail="Introspect ProbOS internals: explain_last, agent_info, system_health, why",
        ),
    ]
    initial_confidence: float = 0.9
    intent_descriptors = [
        IntentDescriptor(name="explain_last", params={}, description="Explain what happened in the last request", requires_reflect=True),
        IntentDescriptor(name="agent_info", params={"agent_type": "...", "agent_id": "..."}, description="Get info about a specific agent", requires_reflect=True),
        IntentDescriptor(name="system_health", params={}, description="Get system health assessment", requires_reflect=True),
        IntentDescriptor(name="why", params={"question": "..."}, description="Explain why ProbOS did something", requires_reflect=True),
        IntentDescriptor(name="introspect_memory", params={}, description="Report episodic memory status — episode count, intent type distribution, success/failure rates, storage backend info", requires_reflect=True),
        IntentDescriptor(name="introspect_system", params={}, description="Report comprehensive system status — agent tiers, pool health, trust network summary, Hebbian routing stats, knowledge store status, dream cycle state", requires_reflect=True),
    ]

    _handled_intents = {"explain_last", "agent_info", "system_health", "why", "introspect_memory", "introspect_system"}

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive -> decide -> act -> report."""
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None

        plan = await self.decide(observation)
        if plan is None:
            return None

        result = await self.act(plan)
        report = await self.report(result)

        success = report.get("success", False)
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
        intent_name = intent.get("intent", "")
        if intent_name not in self._handled_intents:
            return None
        return {
            "intent": intent_name,
            "params": intent.get("params", {}),
        }

    async def decide(self, observation: Any) -> Any:
        return {"action": observation["intent"], "params": observation["params"]}

    async def act(self, plan: Any) -> Any:
        action = plan["action"]
        params = plan["params"]
        rt = self._runtime

        if rt is None:
            return {"success": False, "error": "No runtime reference available"}

        if action == "explain_last":
            return await self._explain_last(rt)
        elif action == "agent_info":
            return self._agent_info(rt, params)
        elif action == "system_health":
            return self._system_health(rt)
        elif action == "why":
            return await self._why(rt, params)
        elif action == "introspect_memory":
            return await self._introspect_memory(rt)
        elif action == "introspect_system":
            return self._introspect_system(rt)

        return {"success": False, "error": f"Unknown introspection action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        return result

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _explain_last(self, rt: Any) -> dict[str, Any]:
        """Explain the most recent NL request."""
        prev = rt._previous_execution
        if prev is not None:
            return self._format_execution(prev)

        # Fallback to episodic memory
        if rt.episodic_memory:
            try:
                episodes = await rt.episodic_memory.recent(k=1)
                if episodes:
                    ep = episodes[0]
                    return {
                        "success": True,
                        "data": {
                            "source": "episodic_memory",
                            "input": ep.user_input,
                            "outcomes": ep.outcomes,
                            "agent_ids": ep.agent_ids,
                            "duration_ms": ep.duration_ms,
                        },
                    }
            except Exception:
                pass

        return {"success": True, "data": {"explanation": "No execution history available."}}

    def _format_execution(self, execution: dict[str, Any]) -> dict[str, Any]:
        """Format an execution result dict for explain_last."""
        dag = execution.get("dag")
        results = execution.get("results", {})

        nodes_info = []
        agent_ids: list[str] = []
        if dag and hasattr(dag, "nodes"):
            for node in dag.nodes:
                node_result = results.get(node.id, {})
                node_info: dict[str, Any] = {
                    "id": node.id,
                    "intent": node.intent,
                    "params": node.params,
                    "status": node.status,
                }
                # Extract agent IDs
                if isinstance(node_result, dict):
                    node_results = node_result.get("results", [])
                    if isinstance(node_results, list):
                        for r in node_results:
                            if hasattr(r, "agent_id"):
                                agent_ids.append(r.agent_id)
                nodes_info.append(node_info)

        return {
            "success": True,
            "data": {
                "source": "execution_history",
                "input": execution.get("input", ""),
                "nodes": nodes_info,
                "agent_ids": agent_ids,
                "node_count": execution.get("node_count", 0),
                "completed_count": execution.get("completed_count", 0),
                "failed_count": execution.get("failed_count", 0),
                "reflection": execution.get("reflection"),
            },
        }

    def _agent_info(self, rt: Any, params: dict[str, Any]) -> dict[str, Any]:
        """Return details about agents matching type or ID."""
        agent_type = params.get("agent_type")
        agent_id = params.get("agent_id")

        agents = []
        if agent_id:
            agent = rt.registry.get(agent_id)
            if agent:
                agents = [agent]
        elif agent_type:
            # Exact match first
            agents = [a for a in rt.registry.all() if a.agent_type == agent_type]
            if not agents:
                # Prefix/substring fallback for partial type names
                needle = agent_type.lower()
                agents = [
                    a for a in rt.registry.all()
                    if needle in a.agent_type.lower() or a.agent_type.lower().startswith(needle)
                ]
        else:
            # No filter — return all agents
            agents = list(rt.registry.all())

        if not agents:
            qualifier = agent_type or agent_id or "all"
            return {
                "success": True,
                "data": {"agents": [], "message": f"No agents found matching: {qualifier}"},
            }

        agent_infos = []
        for agent in agents:
            info: dict[str, Any] = agent.info()

            # Add trust score
            trust = rt.trust_network.get_score(agent.id)
            info["trust_score"] = round(trust, 4)

            # Add Hebbian weight context
            all_weights = rt.hebbian_router.all_weights_typed()
            incoming = sorted(
                [(k[0], v) for k, v in all_weights.items() if k[1] == agent.id],
                key=lambda x: x[1],
                reverse=True,
            )[:3]
            outgoing = sorted(
                [(k[1], v) for k, v in all_weights.items() if k[0] == agent.id],
                key=lambda x: x[1],
                reverse=True,
            )[:3]
            info["hebbian"] = {
                "incoming_top3": [{"source": s, "weight": round(w, 4)} for s, w in incoming],
                "outgoing_top3": [{"target": t, "weight": round(w, 4)} for t, w in outgoing],
                "total_connections": sum(
                    1 for k in all_weights if k[0] == agent.id or k[1] == agent.id
                ),
            }
            agent_infos.append(info)

        return {"success": True, "data": {"agents": agent_infos}}

    def _system_health(self, rt: Any) -> dict[str, Any]:
        """Compute a structured health assessment."""
        # Pool health
        pool_health = []
        for name, pool in rt.pools.items():
            active = len(pool.healthy_agents)
            target = pool.target_size
            pool_health.append({
                "name": name,
                "active": active,
                "target": target,
                "ratio": round(active / target, 2) if target > 0 else 0.0,
            })

        # Trust outliers
        trust_outliers = []
        all_scores = rt.trust_network.all_scores()
        for agent_id, score in all_scores.items():
            if score < 0.3:
                trust_outliers.append({"agent_id": agent_id, "trust": round(score, 4), "flag": "low trust"})
            elif score > 0.9:
                trust_outliers.append({"agent_id": agent_id, "trust": round(score, 4), "flag": "high trust"})

        # Attention depth
        attention_depth = rt.attention.queue_size if rt.attention else 0

        # Cache stats
        cache_stats = {
            "size": rt.workflow_cache.size if rt.workflow_cache else 0,
            "entries": len(rt.workflow_cache.entries) if rt.workflow_cache else 0,
        }

        # Hebbian density
        all_weights = rt.hebbian_router.all_weights_typed()
        agent_count = rt.registry.count
        hebbian_density = (
            len(all_weights) / (agent_count * agent_count)
            if agent_count > 0 else 0.0
        )

        # Overall health (same as shell prompt)
        from probos.types import AgentState
        active_agents = [a for a in rt.registry.all() if a.state == AgentState.ACTIVE]
        overall_health = (
            sum(a.confidence for a in active_agents) / len(active_agents)
            if active_agents else 0.0
        )

        # Dreaming
        dreaming_info: dict[str, Any] = {"enabled": rt.dream_scheduler is not None}
        if rt.dream_scheduler:
            report = rt.dream_scheduler.last_dream_report
            if report:
                dreaming_info["last_report"] = {
                    "episodes_replayed": report.episodes_replayed,
                    "weights_strengthened": report.weights_strengthened,
                    "pre_warm_intents": report.pre_warm_intents,
                }

        return {
            "success": True,
            "data": {
                "pool_health": pool_health,
                "trust_outliers": trust_outliers,
                "attention_depth": attention_depth,
                "cache_stats": cache_stats,
                "hebbian_density": round(hebbian_density, 4),
                "overall_health": round(overall_health, 4),
                "dreaming": dreaming_info,
            },
        }

    async def _why(self, rt: Any, params: dict[str, Any]) -> dict[str, Any]:
        """Answer a 'why' question about ProbOS behavior."""
        question = params.get("question", "")

        if not rt.episodic_memory:
            return {
                "success": True,
                "data": {
                    "matching_episodes": [],
                    "explanation": "No episodic memory available for historical queries.",
                },
            }

        try:
            episodes = await rt.episodic_memory.recall(question, k=5)
        except Exception:
            episodes = []

        matching_episodes = []
        all_agent_ids: set[str] = set()
        for ep in episodes:
            ep_summary = {
                "input": ep.user_input,
                "outcomes": ep.outcomes,
                "agent_ids": ep.agent_ids,
            }
            matching_episodes.append(ep_summary)
            all_agent_ids.update(ep.agent_ids)

        # Build agent context with trust and Hebbian connections
        agent_context: dict[str, Any] = {}
        for aid in all_agent_ids:
            trust_score = rt.trust_network.get_score(aid)
            all_weights = rt.hebbian_router.all_weights_typed()
            top_connections = sorted(
                [(k[1], v) for k, v in all_weights.items() if k[0] == aid],
                key=lambda x: x[1],
                reverse=True,
            )[:3]
            agent_context[aid] = {
                "trust_score": round(trust_score, 4),
                "top_connections": [
                    {"target": t, "weight": round(w, 4)} for t, w in top_connections
                ],
            }

        return {
            "success": True,
            "data": {
                "matching_episodes": matching_episodes,
                "agent_context": agent_context,
            },
        }

    async def _introspect_memory(self, rt: Any) -> dict[str, Any]:
        """Report episodic memory status."""
        if not rt.episodic_memory:
            return {
                "success": True,
                "data": {
                    "enabled": False,
                    "message": "Episodic memory is not enabled.",
                },
            }

        try:
            stats = await rt.episodic_memory.get_stats()
        except Exception as exc:
            return {
                "success": True,
                "data": {
                    "enabled": True,
                    "error": f"Failed to retrieve memory stats: {exc}",
                },
            }

        return {
            "success": True,
            "data": {
                "enabled": True,
                "total_episodes": stats.get("total_episodes", 0),
                "unique_intents": stats.get("unique_intents", 0),
                "intent_distribution": stats.get("intent_distribution", {}),
                "success_rate": stats.get("success_rate"),
                "storage_backend": stats.get("backend", "chromadb"),
            },
        }

    def _introspect_system(self, rt: Any) -> dict[str, Any]:
        """Report comprehensive system status."""
        # Agent count by tier
        tier_counts: dict[str, int] = {"core": 0, "utility": 0, "domain": 0}
        for agent in rt.registry.all():
            t = getattr(agent, "tier", "domain")
            tier_counts[t] = tier_counts.get(t, 0) + 1

        # Trust network summary
        all_scores = rt.trust_network.all_scores()
        trust_values = list(all_scores.values())
        trust_summary: dict[str, Any] = {
            "agent_count": len(trust_values),
        }
        if trust_values:
            trust_summary["mean"] = round(sum(trust_values) / len(trust_values), 4)
            trust_summary["min"] = round(min(trust_values), 4)
            trust_summary["max"] = round(max(trust_values), 4)

        # Hebbian routing
        hebbian_weight_count = rt.hebbian_router.weight_count

        # Pool health
        pool_health = []
        for name, pool in rt.pools.items():
            pool_health.append({
                "name": name,
                "current": len(pool.healthy_agents),
                "target": pool.target_size,
            })

        # Knowledge store
        knowledge_info: dict[str, Any] = {"enabled": rt._knowledge_store is not None}
        if rt._knowledge_store:
            knowledge_info["repo_path"] = str(rt._knowledge_store.repo_path)

        # Dream cycle
        dreaming_info: dict[str, Any] = {"enabled": rt.dream_scheduler is not None}
        if rt.dream_scheduler:
            dreaming_info["state"] = "dreaming" if rt.dream_scheduler.is_dreaming else "idle"

        return {
            "success": True,
            "data": {
                "agents_by_tier": tier_counts,
                "total_agents": rt.registry.count,
                "trust_summary": trust_summary,
                "hebbian_weight_count": hebbian_weight_count,
                "pool_health": pool_health,
                "knowledge": knowledge_info,
                "dreaming": dreaming_info,
            },
        }
