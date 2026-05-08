"""AD-694a: Graph snapshot builder for the spatial explorer.

Extracts the edge-construction logic that previously lived inside the
``/api/ontology/graph`` route handler. The route handler now only marshals
the request and calls ``build_ontology_graph_snapshot``.

Why: the route handler had grown to ~200 lines of business logic — manifest
joins, post resolution, reports_to walking past unfilled manager posts.
That violates SRP (route handlers should orchestrate, not compute) and
makes new graph variants (federation snapshot, time-sliced) harder to add.

Layer position: cross-cutting utility under ``probos.ontology``. Imports
``probos.knowledge.edges`` lazily to avoid a hard dependency.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Any

logger = logging.getLogger(__name__)


async def build_ontology_graph_snapshot(
    *,
    ontology: Any,
    knowledge_edges: Any = None,
    trust_network: Any = None,
    callsign_registry: Any = None,
    include_edges: bool = True,
    max_edges: int = 500,
    max_nodes: int = 200,
    edge_relations: str = "",
) -> dict[str, Any]:
    """Return ``{"nodes", "edges", "generated_at"}`` graph snapshot.

    Args:
        ontology: Ontology service (must expose
            ``get_departments``, ``get_posts`` (optional),
            ``get_crew_manifest``, ``get_all_assignments``).
        knowledge_edges: Optional ``KnowledgeEdgeStore``. When omitted no
            knowledge edges are appended.
        trust_network / callsign_registry: Forwarded to
            ``ontology.get_crew_manifest``.
        include_edges: When False, only assignment-derived edges are
            emitted (knowledge edges skipped).
        max_edges: Cap on knowledge edges fetched from ``knowledge_edges``.
        max_nodes: Final cap on the node list.
        edge_relations: Optional comma-separated allow-list of knowledge
            relations.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # Department nodes
    for dept in ontology.get_departments():
        d = asdict(dept)
        nodes.append(
            {
                "id": d.get("id"),
                "label": d.get("name") or d.get("id"),
                "type": "department",
                "accent_color": d.get("accent_color", "#666680"),
            }
        )

    # Crew manifest -> agent nodes + agent_type -> [agent_id] map
    manifest = ontology.get_crew_manifest(
        trust_network=trust_network,
        callsign_registry=callsign_registry,
    )
    agent_ids_by_type: dict[str, list[str]] = {}
    for entry in manifest:
        nodes.append(
            {
                "id": entry.get("agent_id") or entry.get("agent_type"),
                "label": entry.get("callsign") or entry.get("agent_type"),
                "type": "agent",
                "department": entry.get("department"),
                "rank": entry.get("rank"),
                "trust": entry.get("trust"),
                "post": entry.get("post"),
                "on_watch": entry.get("on_watch", False),
            }
        )
        at = entry.get("agent_type")
        aid = entry.get("agent_id") or at
        if at and aid:
            agent_ids_by_type.setdefault(at, []).append(aid)

    # Post lookup (optional — not all ontology impls expose get_posts)
    posts_by_id: dict[str, Any] = {}
    if hasattr(ontology, "get_posts"):
        try:
            for p in ontology.get_posts():
                posts_by_id[p.id] = p
        except Exception:
            posts_by_id = {}

    assignments_list = list(ontology.get_all_assignments())

    # Build post -> [assigned agent_ids] for reports_to walking. We must
    # walk past unfilled manager posts so e.g. Science crew can connect
    # via dual-hatted first_officer when chief_science is vacant.
    post_to_agent_ids: dict[str, list[str]] = {}
    for a in assignments_list:
        ad = asdict(a)
        at = ad.get("agent_type")
        pid = ad.get("post_id")
        if at and pid:
            post_to_agent_ids.setdefault(pid, []).extend(
                agent_ids_by_type.get(at, [at])
            )

    def _resolve_manager_agent_ids(starting_post_id: str) -> list[str]:
        seen: set[str] = set()
        cur = starting_post_id
        while cur and cur not in seen:
            seen.add(cur)
            ids = post_to_agent_ids.get(cur)
            if ids:
                return ids
            mp = posts_by_id.get(cur)
            if mp is None:
                return []
            cur = getattr(mp, "reports_to", None) or ""
        return []

    # member_of + reports_to edges (always emitted)
    for a in assignments_list:
        ad = asdict(a)
        agent_type = ad.get("agent_type")
        post_id = ad.get("post_id")
        post = posts_by_id.get(post_id) if post_id else None
        agent_ids = agent_ids_by_type.get(agent_type, [])
        if not agent_ids and agent_type:
            agent_ids = [agent_type]
        if post is None:
            # Minimal-ontology fallback: emit legacy agent_type -> post_id edge
            edges.append(
                {
                    "id": f"member_of:{agent_type}:{post_id}",
                    "source": agent_type,
                    "target": post_id,
                    "relation": "member_of",
                    "weight": 1.0,
                }
            )
            continue
        dept_id = post.department_id
        manager_post_id = getattr(post, "reports_to", None)
        for aid in agent_ids:
            if dept_id:
                edges.append(
                    {
                        "id": f"member_of:{aid}:{dept_id}",
                        "source": aid,
                        "target": dept_id,
                        "relation": "member_of",
                        "weight": 1.0,
                    }
                )
            if manager_post_id:
                for mid in _resolve_manager_agent_ids(manager_post_id):
                    if mid == aid:
                        continue
                    edges.append(
                        {
                            "id": f"reports_to:{aid}:{mid}",
                            "source": aid,
                            "target": mid,
                            "relation": "reports_to",
                            "weight": 1.0,
                        }
                    )

    # Optional knowledge edges
    if include_edges and knowledge_edges is not None and max_edges > 0:
        try:
            from probos.knowledge.edges import KnowledgeRelationType

            relation_filter: list[KnowledgeRelationType] | None = None
            if edge_relations:
                wanted = {r.strip() for r in edge_relations.split(",") if r.strip()}
                valid_values = {r.value for r in KnowledgeRelationType}
                relation_filter = [
                    KnowledgeRelationType(r) for r in wanted if r in valid_values
                ]
                if not relation_filter:
                    relation_filter = None
            graph_edges = await knowledge_edges.find_edges(limit=max_edges)
            for ke in graph_edges:
                if relation_filter is not None and ke.relation not in relation_filter:
                    continue
                edges.append(
                    {
                        "id": ke.id,
                        "source": ke.source_id,
                        "target": ke.target_id,
                        "relation": ke.relation.value,
                        "weight": ke.weight,
                        "confidence": ke.confidence,
                        "source_type": ke.source_type.value,
                        "target_type": ke.target_type.value,
                    }
                )
        except Exception as exc:
            logger.warning(
                "AD-694a/AD-520: knowledge_edges.find_edges failed; skipping knowledge edges: %s",
                exc,
            )

    # Truncate node list (edges are kept untouched — they may still
    # reference truncated node ids; clients filter accordingly).
    if max_nodes > 0 and len(nodes) > max_nodes:
        nodes = nodes[:max_nodes]

    return {
        "nodes": nodes,
        "edges": edges,
        "generated_at": time.time(),
    }
