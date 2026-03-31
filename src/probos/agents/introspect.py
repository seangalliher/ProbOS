"""Introspection agent — self-referential queries about ProbOS state."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from probos.substrate.agent import BaseAgent

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime
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
            detail="Introspect ProbOS internals: explain_last, agent_info, team_info, system_health, why, introspect_design",
        ),
    ]
    initial_confidence: float = 0.9
    intent_descriptors = [
        IntentDescriptor(name="explain_last", params={}, description="Explain what happened in the last request", requires_reflect=True),
        IntentDescriptor(name="agent_info", params={"agent_type": "...", "agent_id": "..."}, description="Get info about a specific agent", requires_reflect=True),
        IntentDescriptor(name="team_info", params={"team": "crew team name (e.g. medical, core, utility, self_mod)"}, description="Get info about a crew team (pool group) — health, agent roster, pool statuses", requires_reflect=True),
        IntentDescriptor(name="system_health", params={}, description="Get system health assessment", requires_reflect=True),
        IntentDescriptor(name="why", params={"question": "..."}, description="Explain why ProbOS did something", requires_reflect=True),
        IntentDescriptor(name="introspect_memory", params={}, description="Report episodic memory status — episode count, intent type distribution, success/failure rates, storage backend info", requires_reflect=True),
        IntentDescriptor(name="introspect_system", params={}, description="Report comprehensive system status — agent tiers, pool health, trust network summary, Hebbian routing stats, knowledge store status, dream cycle state", requires_reflect=True),
        IntentDescriptor(name="system_anomalies", params={}, description="Report detected system anomalies — trust outliers, routing shifts, consolidation anomalies, cooperation clusters", requires_reflect=True),
        IntentDescriptor(name="emergent_patterns", params={}, description="Report emergent behavior metrics — cooperation clusters, total correlation (TC_N), routing entropy, capability growth trends", requires_reflect=True),
        IntentDescriptor(name="search_knowledge", params={"query": "...", "types": "..."}, description="Search across all ProbOS knowledge — episodes, agents, skills, workflows, QA reports, system events. Semantic similarity matching.", requires_reflect=True),
        IntentDescriptor(name="introspect_design", params={"question": "question about ProbOS architecture or design"}, description="Answer questions about ProbOS architecture, design, roadmap, project documentation, decisions, progress, and internal structure using source code and project doc knowledge", requires_reflect=True),
    ]

    _handled_intents = {"explain_last", "agent_info", "team_info", "system_health", "why", "introspect_memory", "introspect_system", "system_anomalies", "emergent_patterns", "search_knowledge", "introspect_design"}

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
        elif action == "team_info":
            return self._team_info(rt, params)
        elif action == "system_health":
            return self._system_health(rt)
        elif action == "why":
            return await self._why(rt, params)
        elif action == "introspect_memory":
            return await self._introspect_memory(rt)
        elif action == "introspect_system":
            return self._introspect_system(rt)
        elif action == "system_anomalies":
            return self._system_anomalies(rt)
        elif action == "emergent_patterns":
            return self._emergent_patterns(rt)
        elif action == "search_knowledge":
            return await self._search_knowledge(rt, params)
        elif action == "introspect_design":
            return self._introspect_design(rt, params)

        return {"success": False, "error": f"Unknown introspection action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        return result

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    def _grounded_context(self) -> str:
        """Build grounded self-knowledge context from SystemSelfModel (AD-320).

        Returns a detailed text block of verified runtime facts for use as
        grounding material in introspection responses. More detailed than
        SystemSelfModel.to_context() — includes per-pool breakdowns with
        department associations and full intent listing.
        """
        rt = self._runtime
        if not rt:
            return ""

        try:
            model = rt._build_system_self_model()
        except Exception:
            return ""

        try:
            parts: list[str] = []

            # Identity + health
            parts.append(f"System: ProbOS | Mode: {model.system_mode}")
            if model.uptime_seconds > 0:
                mins = int(model.uptime_seconds // 60)
                parts.append(f"Uptime: {mins} minutes")

            # Topology summary
            parts.append(f"Total pools: {model.pool_count}")
            parts.append(f"Total agents: {model.agent_count}")
            parts.append(f"Registered intents: {model.intent_count}")

            # Departments with their pools
            if model.departments:
                parts.append(f"\nDepartments: {', '.join(model.departments)}")
            if model.pools:
                # Group pools by department
                dept_pools: dict[str, list] = {}
                ungrouped: list = []
                for p in model.pools:
                    if p.department:
                        dept_pools.setdefault(p.department, []).append(p)
                    else:
                        ungrouped.append(p)
                for dept_name, pools in sorted(dept_pools.items()):
                    pool_items = ", ".join(
                        f"{p.name} ({p.agent_type}, {p.agent_count} agents)"
                        for p in pools
                    )
                    parts.append(f"  {dept_name}: {pool_items}")
                if ungrouped:
                    pool_items = ", ".join(
                        f"{p.name} ({p.agent_type}, {p.agent_count} agents)"
                        for p in ungrouped
                    )
                    parts.append(f"  Unassigned: {pool_items}")

            # Intent listing
            try:
                descriptors = rt.decomposer._intent_descriptors
                if descriptors:
                    intent_names = sorted(d.name for d in descriptors)
                    parts.append(f"\nAvailable intents: {', '.join(intent_names)}")
            except Exception:
                pass

            # Health signals
            if model.recent_errors:
                parts.append(f"\nRecent errors: {'; '.join(model.recent_errors)}")
            if model.last_capability_gap:
                parts.append(f"Last capability gap: {model.last_capability_gap}")

            return "\n".join(parts)
        except Exception:
            return ""

    async def _explain_last(self, rt: ProbOSRuntime) -> dict[str, Any]:
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

    def _agent_info(self, rt: ProbOSRuntime, params: dict[str, Any]) -> dict[str, Any]:
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
            if not agents:
                # Pool name fallback — search for agents in pools matching the query
                needle = agent_type.lower()
                for pool_name, pool in rt.pools.items():
                    if needle in pool_name.lower():
                        for aid in pool.healthy_agents:
                            resolved = rt.registry.get(aid)
                            if resolved:
                                agents.append(resolved)
            if not agents and hasattr(rt, 'callsign_registry'):
                # Callsign resolution fallback (BF-013)
                resolved = rt.callsign_registry.resolve(agent_type or agent_id or "")
                if resolved:
                    agents = [a for a in rt.registry.all()
                              if a.agent_type == resolved["agent_type"]]
        else:
            # No filter — return all agents
            agents = list(rt.registry.all())

        if not agents:
            qualifier = agent_type or agent_id or "all"
            result = {
                "success": True,
                "data": {"agents": [], "message": f"No agents found matching: {qualifier}"},
            }
            # Append grounded topology for reflector (AD-320)
            grounded = self._grounded_context()
            if grounded:
                result["data"]["grounded_context"] = grounded
            return result

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

        # Append grounded topology for reflector (AD-320)
        grounded = self._grounded_context()
        if grounded:
            data = {"agents": agent_infos, "grounded_context": grounded}
        else:
            data = {"agents": agent_infos}
        return {"success": True, "data": data}

    def _team_info(self, rt: ProbOSRuntime, params: dict[str, Any]) -> dict[str, Any]:
        """Return details about a crew team (pool group)."""
        team_name = params.get("team", "").strip().lower()

        if not team_name:
            # No specific team — list all teams
            groups = rt.pool_groups.all_groups()
            if not groups:
                result = {
                    "success": True,
                    "data": {"message": "No crew teams registered."},
                }
                # Append grounded topology for reflector (AD-320)
                grounded = self._grounded_context()
                if grounded:
                    result["data"]["grounded_context"] = grounded
                return result
            team_summaries = []
            for group in groups:
                health = rt.pool_groups.group_health(group.name, rt.pools)
                team_summaries.append({
                    "name": group.name,
                    "display_name": group.display_name,
                    "total_agents": health.get("total_agents", 0),
                    "healthy_agents": health.get("healthy_agents", 0),
                    "health_ratio": health.get("health_ratio", 1.0),
                    "pool_count": len(group.pool_names),
                })
            result = {
                "success": True,
                "data": {"teams": team_summaries, "count": len(team_summaries)},
            }
            # Append grounded topology for reflector (AD-320)
            grounded = self._grounded_context()
            if grounded:
                result["data"]["grounded_context"] = grounded
            return result

        # Look up the specific team
        group = rt.pool_groups.get_group(team_name)

        # Fuzzy fallback: try substring match on group names
        if group is None:
            for g in rt.pool_groups.all_groups():
                if team_name in g.name or team_name in g.display_name.lower():
                    group = g
                    break

        if group is None:
            return {
                "success": True,
                "data": {
                    "message": f"No crew team found matching '{team_name}'.",
                    "available_teams": [g.name for g in rt.pool_groups.all_groups()],
                },
            }

        # Get aggregate health
        health = rt.pool_groups.group_health(group.name, rt.pools)

        # Get individual agent details for all pools in this group
        agent_details = []
        for pool_name in sorted(group.pool_names):
            pool = rt.pools.get(pool_name)
            if pool is None:
                continue
            for agent_id in pool.healthy_agents:
                agent = rt.registry.get(agent_id)
                if agent is None:
                    continue
                info: dict[str, Any] = agent.info()
                trust = rt.trust_network.get_score(agent_id)
                info["trust_score"] = round(trust, 4)
                info["pool"] = pool_name
                agent_details.append(info)

        result = {
            "success": True,
            "data": {
                "team": {
                    "name": group.name,
                    "display_name": group.display_name,
                    "exclude_from_scaler": group.exclude_from_scaler,
                },
                "health": {
                    "total_agents": health.get("total_agents", 0),
                    "healthy_agents": health.get("healthy_agents", 0),
                    "health_ratio": round(health.get("health_ratio", 1.0), 4),
                },
                "pools": health.get("pools", {}),
                "agents": agent_details,
            },
        }
        # Append grounded topology for reflector (AD-320)
        grounded = self._grounded_context()
        if grounded:
            result["data"]["grounded_context"] = grounded
        return result

    def _system_health(self, rt: ProbOSRuntime) -> dict[str, Any]:
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

        result = {
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
        # Append grounded topology for reflector (AD-320)
        grounded = self._grounded_context()
        if grounded:
            result["data"]["grounded_context"] = grounded
        return result

    async def _why(self, rt: ProbOSRuntime, params: dict[str, Any]) -> dict[str, Any]:
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

    async def _introspect_memory(self, rt: ProbOSRuntime) -> dict[str, Any]:
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
                "total_episodes": stats.get("total", 0),
                "unique_intents": len(stats.get("intent_distribution", {})),
                "intent_distribution": stats.get("intent_distribution", {}),
                "success_rate": stats.get("avg_success_rate"),
                "storage_backend": stats.get("backend", "chromadb"),
            },
        }

    def _introspect_system(self, rt: ProbOSRuntime) -> dict[str, Any]:
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

        result = {
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
        # Append grounded topology for reflector (AD-320)
        grounded = self._grounded_context()
        if grounded:
            result["data"]["grounded_context"] = grounded
        return result

    def _system_anomalies(self, rt: ProbOSRuntime) -> dict[str, Any]:
        """Report currently detected anomalies and patterns."""
        detector = getattr(rt, "_emergent_detector", None)
        if detector is None:
            return {
                "success": True,
                "data": {"message": "Emergent detection not available"},
            }

        patterns = detector.analyze()
        pattern_dicts = [
            {
                "pattern_type": p.pattern_type,
                "description": p.description,
                "confidence": round(p.confidence, 3),
                "severity": p.severity,
                "evidence": p.evidence,
            }
            for p in patterns
        ]

        return {
            "success": True,
            "data": {
                "anomaly_count": len(pattern_dicts),
                "patterns": pattern_dicts,
            },
        }

    def _emergent_patterns(self, rt: ProbOSRuntime) -> dict[str, Any]:
        """Report system dynamics overview including TC_N and trends."""
        detector = getattr(rt, "_emergent_detector", None)
        if detector is None:
            return {
                "success": True,
                "data": {"message": "Emergent detection not available"},
            }

        snapshot = detector.get_snapshot()
        summary = detector.summary()

        # Build trend data from snapshot history
        trends: dict[str, list] = {"tc_n": [], "routing_entropy": []}
        for snap in list(detector._history)[-10:]:
            trends["tc_n"].append(round(snap.tc_n, 4))
            trends["routing_entropy"].append(round(snap.routing_entropy, 4))

        return {
            "success": True,
            "data": {
                "snapshot": {
                    "tc_n": round(snapshot.tc_n, 4),
                    "routing_entropy": round(snapshot.routing_entropy, 4),
                    "capability_count": snapshot.capability_count,
                    "cooperation_clusters": len(snapshot.cooperation_clusters),
                    "dream_consolidation_rate": round(snapshot.dream_consolidation_rate, 2),
                    "trust_distribution": {
                        k: round(v, 4) if isinstance(v, float) else v
                        for k, v in snapshot.trust_distribution.items()
                        if k != "per_agent"
                    },
                },
                "summary": summary,
                "trends": trends,
            },
        }

    async def _search_knowledge(self, rt: ProbOSRuntime, params: dict) -> dict[str, Any]:
        """Search across all ProbOS knowledge types."""
        query = params.get("query", "")
        if not query:
            return {
                "success": False,
                "error": "Missing 'query' parameter",
            }

        results: list = []

        # Search semantic layer (episodes, agents, skills, workflows)
        layer = getattr(rt, "_semantic_layer", None)
        if layer is not None:
            # Parse optional types filter
            types_str = params.get("types", "")
            types: list[str] | None = None
            if types_str:
                types = [t.strip() for t in types_str.split(",") if t.strip()]
            results = await layer.search(query, types=types, limit=10)

        # Also search project docs via CodebaseIndex (AD-301)
        doc_snippets: list[dict[str, str]] = []
        codebase_index = getattr(rt, "codebase_index", None)
        if codebase_index is not None:
            from probos.cognitive.codebase_index import _STOP_WORDS

            arch_data = codebase_index.query(query)
            matching_files = arch_data.get("matching_files", [])

            query_keywords = [
                w for w in query.lower().split()
                if w not in _STOP_WORDS and len(w) > 1
            ]

            for file_info in matching_files[:3]:
                file_path = file_info.get("path", "")
                if not file_path:
                    continue
                if file_path.startswith("docs:"):
                    source = codebase_index.read_doc_sections(file_path, query_keywords)
                else:
                    source = codebase_index.read_source(file_path, end_line=80)
                if source:
                    doc_snippets.append({"path": file_path, "source": source})

        if doc_snippets:
            logger.info("search_knowledge found %d doc snippets: %s",
                        len(doc_snippets),
                        [s["path"] for s in doc_snippets])

        if not results and not doc_snippets:
            return {
                "success": True,
                "data": {
                    "message": "Knowledge search not available — no semantic layer or codebase index found.",
                    "query": query,
                },
            }

        return {
            "success": True,
            "data": {
                "query": query,
                "results": results,
                "count": len(results),
                "doc_snippets": doc_snippets,
            },
        }

    def _introspect_design(self, rt: ProbOSRuntime, params: dict[str, Any]) -> dict[str, Any]:
        """Answer architectural questions using codebase knowledge."""
        question = params.get("question", "")
        if not question:
            return {"success": False, "error": "No question provided"}

        codebase_index = getattr(rt, "codebase_index", None)
        if codebase_index is None:
            return {
                "success": True,
                "data": {
                    "message": "Codebase knowledge not available. Cannot introspect source architecture.",
                },
            }

        # Query architecture for the concept
        arch_data = codebase_index.query(question)
        agent_map = codebase_index.get_agent_map()
        layer_map = codebase_index.get_layer_map()

        # Read source snippets from the top matching files (AD-297)
        source_snippets: list[dict[str, str]] = []
        matching_files = arch_data.get("matching_files", [])

        # Extract keywords for section targeting (AD-300)
        from probos.cognitive.codebase_index import _STOP_WORDS
        query_keywords = [
            w for w in question.lower().split()
            if w not in _STOP_WORDS and len(w) > 1
        ]

        for file_info in matching_files[:3]:  # top 3 most relevant files
            file_path = file_info.get("path", "")
            if not file_path:
                continue

            # Use section-targeted reading for docs, fixed 80-line for source (AD-300)
            if file_path.startswith("docs:"):
                source = codebase_index.read_doc_sections(file_path, query_keywords)
            else:
                source = codebase_index.read_source(file_path, end_line=80)

            if source:
                source_snippets.append({
                    "path": file_path,
                    "source": source,
                })

        return {
            "success": True,
            "data": {
                "question": question,
                "architecture_context": arch_data,
                "agent_count": len(agent_map) if agent_map else 0,
                "layers": list(layer_map.keys()) if layer_map else [],
                "source_snippets": source_snippets,
            },
        }
