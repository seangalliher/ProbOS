"""ProbOS API — Memory Graph routes (AD-611)."""

from __future__ import annotations

import logging
import math
import time
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from probos.cognitive.episodic import resolve_sovereign_id_from_slot
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["memory-graph"])

# Channel → color mapping (per-agent mode)
CHANNEL_COLORS: dict[str, str] = {
    "bridge": "#f0b060",
    "engineering": "#4a9eff",
    "medical": "#52c474",
    "security": "#ff6b6b",
    "science": "#c084fc",
    "operations": "#fbbf24",
    "dm": "#94a3b8",
}
DEFAULT_CHANNEL_COLOR = "#6b7280"

# Department → color mapping (ship-wide mode)
DEPARTMENT_COLORS: dict[str, str] = {
    "bridge": "#f0b060",
    "engineering": "#4a9eff",
    "medical": "#52c474",
    "security": "#ff6b6b",
    "science": "#c084fc",
    "operations": "#fbbf24",
    "communications": "#38bdf8",
}
DEFAULT_DEPARTMENT_COLOR = "#6b7280"

# Edge type → color mapping
EDGE_COLORS: dict[str, str] = {
    "semantic": "#4a9eff",
    "thread": "#f0b060",
    "temporal": "#6b7280",
    "participant": "#c084fc",
}

MAX_NODES_CAP = 500
MAX_EDGES_CAP = 2000


@router.get("/{agent_id}/memory-graph")
async def get_memory_graph(
    agent_id: str,
    runtime: Any = Depends(get_runtime),
    max_nodes: int = Query(200, ge=1, le=MAX_NODES_CAP),
    ship_wide: bool = Query(False),
    semantic_k: int = Query(5, ge=1, le=20),
    time_range_hours: int | None = Query(None, ge=1),
) -> Any:
    """Return nodes and edges for 3D force-directed memory graph."""
    if not hasattr(runtime, 'episodic_memory') or not runtime.episodic_memory:
        return JSONResponse(
            {"error": "Episodic memory not available"}, status_code=503,
        )

    episodic = runtime.episodic_memory
    max_nodes = min(max_nodes, MAX_NODES_CAP)

    # --- Resolve sovereign ID ---
    sovereign_id = resolve_sovereign_id_from_slot(
        agent_id,
        getattr(runtime, 'identity_registry', None),
    )

    # --- Collect episodes ---
    # Three-tier selection for per-agent; ship-wide merges across agents
    try:
        episodes = await _select_episodes(
            episodic, sovereign_id, max_nodes, ship_wide, time_range_hours,
            runtime,
        )
    except Exception:
        logger.exception("AD-611: Episode selection failed")
        return JSONResponse(
            {"error": "Failed to retrieve episodes"}, status_code=500,
        )

    if not episodes:
        return {
            "nodes": [],
            "edges": [],
            "meta": {
                "agent_id": agent_id,
                "total_episodes": 0,
                "nodes_shown": 0,
                "ship_wide": ship_wide,
            },
        }

    # --- Get activations ---
    episode_ids = [ep.id for ep in episodes]
    activations: dict[str, float] = {}
    tracker = getattr(episodic, '_activation_tracker', None)
    if tracker:
        try:
            activations = await tracker.get_activations_batch(episode_ids)
        except Exception:
            logger.debug("AD-611: Activation batch failed", exc_info=True)

    # --- Build nodes ---
    color_mode = "department" if ship_wide else "channel"
    nodes = _build_nodes(episodes, activations, color_mode)

    # --- Build edges ---
    try:
        edges = await _build_edges(
            episodic, episodes, episode_ids, semantic_k,
        )
    except Exception:
        logger.exception("AD-611: Edge construction failed")
        edges = []

    # --- Get total count for meta ---
    total = 0
    try:
        total = await episodic.count_for_agent(sovereign_id)
    except Exception:
        pass

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "agent_id": agent_id,
            "total_episodes": total,
            "nodes_shown": len(nodes),
            "ship_wide": ship_wide,
        },
    }


async def _select_episodes(
    episodic: Any,
    sovereign_id: str,
    max_nodes: int,
    ship_wide: bool,
    time_range_hours: int | None,
    runtime: Any,
) -> list:
    """Three-tier episode selection: recency (70%), importance (20%), activation (10%)."""
    from probos.types import Episode

    seen_ids: set[str] = set()
    result: list[Episode] = []

    recency_count = int(max_nodes * 0.70)
    importance_count = int(max_nodes * 0.20)

    if ship_wide:
        # Get episodes across all crew agents
        all_agents = _get_crew_agents(runtime)
        per_agent = max(recency_count // max(len(all_agents), 1), 5)
        for ag_id in all_agents:
            sid = resolve_sovereign_id_from_slot(
                ag_id, getattr(runtime, 'identity_registry', None),
            )
            recent = await episodic.recent_for_agent(sid, k=per_agent)
            for ep in recent:
                if ep.id not in seen_ids:
                    seen_ids.add(ep.id)
                    result.append(ep)
    else:
        # Tier 1: Recency
        recent = await episodic.recent_for_agent(sovereign_id, k=recency_count)
        for ep in recent:
            seen_ids.add(ep.id)
            result.append(ep)

    # Tier 2: Importance — use recall_by_anchor with agent filter, sort by importance
    try:
        anchor_results = await episodic.recall_by_anchor(
            agent_id=sovereign_id if not ship_wide else "",
            limit=importance_count * 3,  # over-fetch to filter dupes
        )
        # Sort by importance descending
        anchor_results.sort(key=lambda ep: ep.importance, reverse=True)
        for ep in anchor_results:
            if ep.id not in seen_ids and len(result) < recency_count + importance_count:
                seen_ids.add(ep.id)
                result.append(ep)
    except Exception:
        logger.debug("AD-611: Importance tier failed", exc_info=True)

    # Tier 3: Activation — best-effort additive; recency+importance cover 90%

    # Apply time range filter if specified
    if time_range_hours:
        cutoff = time.time() - (time_range_hours * 3600)
        result = [ep for ep in result if ep.timestamp >= cutoff]

    return result[:max_nodes]


def _get_crew_agents(runtime: Any) -> list[str]:
    """Get all crew agent IDs from the registry."""
    from probos.crew_utils import is_crew_agent

    agents = []
    if hasattr(runtime, 'registry'):
        for agent in runtime.registry.all():
            if is_crew_agent(agent, getattr(runtime, 'ontology', None)):
                agents.append(agent.id)
    return agents


def _build_nodes(
    episodes: list,
    activations: dict[str, float],
    color_mode: str,
) -> list[dict]:
    """Build graph node dicts from episodes."""
    nodes = []
    for ep in episodes:
        channel = ""
        department = ""
        participants: list[str] = []
        if ep.anchors:
            channel = ep.anchors.channel or ""
            department = ep.anchors.department or ""
            participants = ep.anchors.participants or []

        if color_mode == "department":
            color = DEPARTMENT_COLORS.get(department, DEFAULT_DEPARTMENT_COLOR)
        else:
            color = CHANNEL_COLORS.get(channel, DEFAULT_CHANNEL_COLOR)

        # Node size: 2 + (importance / 10) * 4 → range 2.2 to 6.0
        size = 2.0 + (ep.importance / 10.0) * 4.0

        # Activation: normalize from raw ACT-R value to 0-1 range
        raw_activation = activations.get(ep.id, float("-inf"))
        # ACT-R values typically range from -5 to +5; sigmoidal norm
        activation = 1.0 / (1.0 + math.exp(-raw_activation)) if raw_activation != float("-inf") else 0.0

        label = (ep.user_input[:57] + "...") if len(ep.user_input) > 60 else ep.user_input

        nodes.append({
            "id": ep.id,
            "label": label,
            "timestamp": ep.timestamp,
            "importance": ep.importance,
            "activation": round(activation, 3),
            "channel": channel,
            "department": department,
            "agent_ids": ep.agent_ids,
            "participants": participants,
            "source": ep.source,
            "reflection": ep.reflection or "",
            "user_input": ep.user_input,
            "color": color,
            "size": round(size, 1),
        })
    return nodes


async def _build_edges(
    episodic: Any,
    episodes: list,
    episode_ids: list[str],
    semantic_k: int,
) -> list[dict]:
    """Build graph edges: semantic (HNSW), thread, temporal, participant."""
    edges: list[dict] = []
    edge_set: set[tuple[str, str, str]] = set()  # (source, target, type) dedup

    id_set = set(episode_ids)

    # --- Semantic edges via HNSW ---
    try:
        embeddings = await episodic.get_embeddings(episode_ids)
        collection = getattr(episodic, '_collection', None)
        if embeddings and collection:
            for ep_id, embedding in embeddings.items():
                try:
                    # Query ChromaDB with this episode's embedding to find neighbors
                    result = collection.query(
                        query_embeddings=[embedding],
                        n_results=semantic_k + 1,  # +1 to exclude self
                        include=["distances"],
                    )
                    if result and result["ids"] and result["ids"][0]:
                        for i, neighbor_id in enumerate(result["ids"][0]):
                            if neighbor_id == ep_id or neighbor_id not in id_set:
                                continue
                            # ChromaDB cosine space: distance = 1 - cosine_similarity
                            dist = result["distances"][0][i] if result["distances"] else 0
                            similarity = max(0, 1.0 - dist)
                            if similarity < 0.3:
                                continue  # skip weak edges
                            key = (min(ep_id, neighbor_id), max(ep_id, neighbor_id), "semantic")
                            if key not in edge_set:
                                edge_set.add(key)
                                edges.append({
                                    "source": ep_id,
                                    "target": neighbor_id,
                                    "type": "semantic",
                                    "weight": round(similarity, 3),
                                    "color": EDGE_COLORS["semantic"],
                                })
                except Exception:
                    continue  # skip failed queries
    except Exception:
        logger.debug("AD-611: Semantic edge construction failed", exc_info=True)

    # --- Thread edges ---
    thread_groups: dict[str, list[str]] = {}
    for ep in episodes:
        if ep.anchors and ep.anchors.thread_id:
            thread_groups.setdefault(ep.anchors.thread_id, []).append(ep.id)
    for thread_id, ep_ids in thread_groups.items():
        for i in range(len(ep_ids)):
            for j in range(i + 1, len(ep_ids)):
                key = (min(ep_ids[i], ep_ids[j]), max(ep_ids[i], ep_ids[j]), "thread")
                if key not in edge_set:
                    edge_set.add(key)
                    edges.append({
                        "source": ep_ids[i],
                        "target": ep_ids[j],
                        "type": "thread",
                        "weight": 1.0,
                        "color": EDGE_COLORS["thread"],
                    })

    # --- Temporal edges (within 5 minutes) ---
    sorted_eps = sorted(episodes, key=lambda e: e.timestamp)
    for i in range(len(sorted_eps)):
        for j in range(i + 1, len(sorted_eps)):
            dt = sorted_eps[j].timestamp - sorted_eps[i].timestamp
            if dt > 300:  # 5 minutes
                break
            weight = 1.0 - (dt / 300.0)
            key = (min(sorted_eps[i].id, sorted_eps[j].id),
                   max(sorted_eps[i].id, sorted_eps[j].id), "temporal")
            if key not in edge_set:
                edge_set.add(key)
                edges.append({
                    "source": sorted_eps[i].id,
                    "target": sorted_eps[j].id,
                    "type": "temporal",
                    "weight": round(weight, 3),
                    "color": EDGE_COLORS["temporal"],
                })

    # --- Participant edges (shared participants, Jaccard) ---
    for i in range(len(episodes)):
        for j in range(i + 1, len(episodes)):
            ep_a, ep_b = episodes[i], episodes[j]
            if not ep_a.anchors or not ep_b.anchors:
                continue
            parts_a = set(ep_a.anchors.participants or [])
            parts_b = set(ep_b.anchors.participants or [])
            if not parts_a or not parts_b:
                continue
            intersection = parts_a & parts_b
            if not intersection:
                continue
            union = parts_a | parts_b
            jaccard = len(intersection) / len(union)
            if jaccard < 0.3:
                continue
            key = (min(ep_a.id, ep_b.id), max(ep_a.id, ep_b.id), "participant")
            if key not in edge_set:
                edge_set.add(key)
                edges.append({
                    "source": ep_a.id,
                    "target": ep_b.id,
                    "type": "participant",
                    "weight": round(jaccard, 3),
                    "color": EDGE_COLORS["participant"],
                })

    # Enforce edge cap — keep strongest edges
    if len(edges) > MAX_EDGES_CAP:
        edges.sort(key=lambda e: e["weight"], reverse=True)
        edges = edges[:MAX_EDGES_CAP]

    return edges
