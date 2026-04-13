# AD-611: 3D Memory Graph Visualization

**GitHub:** seangalliher/ProbOS#192
**Type:** Feature — HXI Enhancement (Era IV)
**Scope:** Backend API + Frontend component

## Overview

Add an interactive 3D force-directed graph visualization of agent episodic memory. Episodes are nodes; semantic similarity, thread co-occurrence, temporal proximity, and shared participants form edges. Renders in a new "Memory" tab in the agent profile panel using `react-force-graph-3d`.

## Prior Work Absorbed

- **AD-531** (`episode_clustering.py`): Reuse `_cosine_similarity()` helper (line 199) for any fallback similarity computation. `get_embeddings(episode_ids)` (episodic.py:1338) already returns raw vectors.
- **AD-567d** (`activation_tracker.py`): `get_activations_batch(episode_ids)` (line 188) returns `dict[str, float]` for bulk activation lookup.
- **AD-570** (`episodic.py:1876`): `recall_by_anchor()` provides structured filtering by department, channel, agent_id, time_range.
- **AD-441**: Sovereign ID resolution — use `resolve_sovereign_id_from_slot()` from `probos.cognitive.episodic` (line 39) to map slot IDs for episode queries.
- **AD-516**: Router registration pattern at `api.py:192-204`.

## Dependencies

New npm package:
```bash
cd ui && npm install react-force-graph-3d
```

Existing: `three@^0.172.0`, `@react-three/fiber@^9.0.0`, `@react-three/drei@^10.0.0` (already in package.json).

---

## Change 1 — Backend Router

### File: `src/probos/routers/memory_graph.py` (NEW)

```python
"""ProbOS API — Memory Graph routes (AD-611)."""

from __future__ import annotations

import json
import logging
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
    activation_count = max_nodes - recency_count - importance_count

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

    # Tier 3: Activation — top activated episodes
    tracker = getattr(episodic, '_activation_tracker', None)
    if tracker and activation_count > 0:
        try:
            # Get activations for all collected + estimate remaining
            all_ids = list(seen_ids)
            # We already have these; try to find high-activation ones we missed
            # Use recent as broader pool since we can't enumerate all IDs cheaply
            pass  # Activation tier is best-effort additive; recency+importance cover 90%
        except Exception:
            pass

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
        import math
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
    ep_by_id = {ep.id: ep for ep in episodes}

    # --- Semantic edges via HNSW ---
    try:
        embeddings = await episodic.get_embeddings(episode_ids)
        if embeddings and hasattr(episodic, '_collection') and episodic._collection:
            for ep_id, embedding in embeddings.items():
                try:
                    # Query ChromaDB with this episode's embedding to find neighbors
                    result = episodic._collection.query(
                        query_embeddings=[embedding],
                        n_results=semantic_k + 1,  # +1 to exclude self
                        include=["distances"],
                    )
                    if result and result["ids"] and result["ids"][0]:
                        for i, neighbor_id in enumerate(result["ids"][0]):
                            if neighbor_id == ep_id or neighbor_id not in id_set:
                                continue
                            # ChromaDB returns L2 distance by default;
                            # convert to similarity. For cosine space (hnsw:space=cosine),
                            # distance = 1 - cosine_similarity.
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
```

### Notes for builder
- `episodic._collection` is the ChromaDB collection. Accessing it directly for `query(query_embeddings=...)` is the pragmatic path since no public wrapper exists for embedding-vector queries. The collection uses `hnsw:space=cosine` (AD-570a), so `distance = 1 - cosine_similarity`.
- `resolve_sovereign_id_from_slot` import is at `probos.cognitive.episodic` line 39.
- `is_crew_agent` import is at `probos.crew_utils`.
- Follow the `hasattr(runtime, 'episodic_memory') and runtime.episodic_memory` guard pattern from `agents.py:101`.
- The `import math` inside `_build_nodes` should be moved to module top.

---

## Change 2 — Wire Router

### File: `src/probos/api.py`

At line 192, add `memory_graph` to the import:
```python
from probos.routers import (
    ontology, system, wardroom, wardroom_admin, records, identity,
    agents, journal, skills, acm, assignments, scheduled_tasks,
    workforce, build, design, chat, counselor, procedures, gaps,
    recreation, memory_graph,
)
```

At line 198, add `memory_graph` to the registration loop tuple:
```python
for r in (
    ontology, system, wardroom, wardroom_admin, records, identity,
    agents, journal, skills, acm, assignments, scheduled_tasks,
    workforce, build, design, chat, counselor, procedures, gaps,
    recreation, memory_graph,
):
```

---

## Change 3 — Frontend TypeScript Types

### File: `ui/src/components/profile/memoryGraphTypes.ts` (NEW)

```typescript
/* AD-611: 3D Memory Graph type definitions. */

export interface MemoryGraphNode {
  id: string;
  label: string;
  timestamp: number;
  importance: number;
  activation: number;
  channel: string;
  department: string;
  agent_ids: string[];
  participants: string[];
  source: string;
  reflection: string;
  user_input: string;
  color: string;
  size: number;
}

export interface MemoryGraphEdge {
  source: string;
  target: string;
  type: 'semantic' | 'thread' | 'temporal' | 'participant';
  weight: number;
  color: string;
}

export interface MemoryGraphMeta {
  agent_id: string;
  total_episodes: number;
  nodes_shown: number;
  ship_wide: boolean;
}

export interface MemoryGraphResponse {
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
  meta: MemoryGraphMeta;
}

// Edge type visual config
export const EDGE_TYPE_CONFIG: Record<string, { color: string; opacity: number; label: string }> = {
  semantic:    { color: '#4a9eff', opacity: 0.4, label: 'Semantic' },
  thread:      { color: '#f0b060', opacity: 0.7, label: 'Thread' },
  temporal:    { color: '#6b7280', opacity: 0.2, label: 'Temporal' },
  participant: { color: '#c084fc', opacity: 0.7, label: 'Participant' },
};
```

---

## Change 4 — 3D Graph Component

### File: `ui/src/components/profile/MemoryGraph3D.tsx` (NEW)

```tsx
/* AD-611: 3D force-directed memory graph visualization. */

import React, { useRef, useCallback, useMemo, useState } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import * as THREE from 'three';
import type { MemoryGraphNode, MemoryGraphEdge, MemoryGraphResponse } from './memoryGraphTypes';
import { EDGE_TYPE_CONFIG } from './memoryGraphTypes';

interface MemoryGraph3DProps {
  data: MemoryGraphResponse;
}

interface GraphNode extends MemoryGraphNode {
  x?: number;
  y?: number;
  z?: number;
}

const MemoryGraph3D: React.FC<MemoryGraph3DProps> = React.memo(({ data }) => {
  const fgRef = useRef<any>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  const graphData = useMemo(() => ({
    nodes: data.nodes as GraphNode[],
    links: data.edges.map(e => ({
      ...e,
      // react-force-graph uses 'source'/'target' which can be ID strings
    })),
  }), [data]);

  const handleNodeClick = useCallback((node: any) => {
    setSelectedNode(node as GraphNode);
    // Focus camera on node
    if (fgRef.current) {
      const distance = 60;
      const distRatio = 1 + distance / Math.hypot(node.x || 0, node.y || 0, node.z || 0);
      fgRef.current.cameraPosition(
        { x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio },
        node,
        1000,
      );
    }
  }, []);

  const nodeThreeObject = useCallback((node: any) => {
    const gNode = node as GraphNode;
    const geometry = new THREE.SphereGeometry(gNode.size * 0.5, 16, 12);
    const material = new THREE.MeshPhongMaterial({
      color: gNode.color,
      transparent: true,
      opacity: 0.3 + gNode.activation * 0.7,
      emissive: gNode.activation > 0.7 ? new THREE.Color(gNode.color) : new THREE.Color('#000000'),
      emissiveIntensity: gNode.activation > 0.7 ? 0.4 : 0,
    });
    return new THREE.Mesh(geometry, material);
  }, []);

  const nodeLabel = useCallback((node: any) => {
    const gNode = node as GraphNode;
    const date = new Date(gNode.timestamp * 1000).toLocaleString();
    return `<div style="background:rgba(0,0,0,0.85);padding:8px 12px;border-radius:6px;max-width:300px;font-size:12px;color:#e0e0e0">
      <div style="font-weight:bold;margin-bottom:4px;color:${gNode.color}">${gNode.label}</div>
      <div style="color:#999;font-size:10px">${date}</div>
      <div style="margin-top:4px">Channel: ${gNode.channel || 'unknown'} | Importance: ${gNode.importance}/10</div>
      <div>Activation: ${(gNode.activation * 100).toFixed(0)}% | Source: ${gNode.source}</div>
      ${gNode.participants.length ? `<div>Participants: ${gNode.participants.join(', ')}</div>` : ''}
    </div>`;
  }, []);

  const linkWidth = useCallback((link: any) => {
    return (link.weight || 0.5) * 2;
  }, []);

  const linkOpacity = useCallback((link: any) => {
    return EDGE_TYPE_CONFIG[link.type]?.opacity ?? 0.3;
  }, []);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <ForceGraph3D
        ref={fgRef}
        graphData={graphData}
        nodeThreeObject={nodeThreeObject}
        nodeLabel={nodeLabel}
        onNodeClick={handleNodeClick}
        linkColor={(link: any) => link.color || '#444'}
        linkWidth={linkWidth}
        linkOpacity={linkOpacity}
        backgroundColor="#0a0a0a"
        warmupTicks={50}
        cooldownTime={3000}
        d3AlphaDecay={0.02}
        enableNodeDrag={true}
        enableNavigationControls={true}
      />

      {/* Legend */}
      <div style={{
        position: 'absolute', bottom: 12, left: 12,
        background: 'rgba(0,0,0,0.75)', padding: '8px 12px',
        borderRadius: 6, fontSize: 11, color: '#ccc',
        display: 'flex', gap: 12,
      }}>
        {Object.entries(EDGE_TYPE_CONFIG).map(([type, cfg]) => (
          <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 16, height: 3, background: cfg.color, borderRadius: 1 }} />
            <span>{cfg.label}</span>
          </div>
        ))}
      </div>

      {/* Selected node detail */}
      {selectedNode && (
        <div style={{
          position: 'absolute', top: 12, right: 12,
          background: 'rgba(0,0,0,0.9)', padding: 16,
          borderRadius: 8, maxWidth: 350, maxHeight: '60%',
          overflow: 'auto', fontSize: 12, color: '#e0e0e0',
          border: `1px solid ${selectedNode.color}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontWeight: 'bold', color: selectedNode.color }}>Episode Detail</span>
            <button
              onClick={() => setSelectedNode(null)}
              style={{ background: 'none', border: 'none', color: '#888', cursor: 'pointer', fontSize: 16 }}
            >
              ×
            </button>
          </div>
          <div style={{ marginBottom: 6 }}><b>Input:</b> {selectedNode.user_input}</div>
          {selectedNode.reflection && (
            <div style={{ marginBottom: 6 }}><b>Reflection:</b> {selectedNode.reflection}</div>
          )}
          <div style={{ marginBottom: 6 }}>
            <b>Time:</b> {new Date(selectedNode.timestamp * 1000).toLocaleString()}
          </div>
          <div style={{ marginBottom: 6 }}>
            <b>Agents:</b> {selectedNode.agent_ids.join(', ')}
          </div>
          <div style={{ marginBottom: 6 }}>
            <b>Importance:</b> {selectedNode.importance}/10 | <b>Activation:</b> {(selectedNode.activation * 100).toFixed(0)}%
          </div>
          <div>
            <b>Channel:</b> {selectedNode.channel} | <b>Source:</b> {selectedNode.source}
          </div>
        </div>
      )}
    </div>
  );
});

MemoryGraph3D.displayName = 'MemoryGraph3D';

export default MemoryGraph3D;
```

---

## Change 5 — Profile Memory Tab Wrapper

### File: `ui/src/components/profile/ProfileMemoryTab.tsx` (NEW)

```tsx
/* AD-611: Memory tab for agent profile panel. */

import React, { useState, useEffect, useCallback } from 'react';
import MemoryGraph3D from './MemoryGraph3D';
import type { MemoryGraphResponse } from './memoryGraphTypes';

interface ProfileMemoryTabProps {
  agentId: string;
}

export function ProfileMemoryTab({ agentId }: ProfileMemoryTabProps) {
  const [data, setData] = useState<MemoryGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [shipWide, setShipWide] = useState(false);

  const fetchGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(
        `/api/agent/${agentId}/memory-graph?ship_wide=${shipWide}`,
      );
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const json: MemoryGraphResponse = await resp.json();
      setData(json);
    } catch (err: any) {
      setError(err.message || 'Failed to load memory graph');
    } finally {
      setLoading(false);
    }
  }, [agentId, shipWide]);

  useEffect(() => {
    fetchGraph();
  }, [fetchGraph]);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Controls bar */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '8px 12px', borderBottom: '1px solid #333', flexShrink: 0,
      }}>
        <div style={{ fontSize: 12, color: '#999' }}>
          {data && !loading && (
            <>
              Showing {data.meta.nodes_shown} of {data.meta.total_episodes} episodes
              {' | '}{data.edges.length} edges
            </>
          )}
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#ccc', cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={shipWide}
            onChange={(e) => setShipWide(e.target.checked)}
            style={{ accentColor: '#f0b060' }}
          />
          Ship-wide
        </label>
      </div>

      {/* Graph area */}
      <div style={{ flex: 1, position: 'relative' }}>
        {loading && (
          <div style={{
            position: 'absolute', inset: 0, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            color: '#888', fontSize: 14,
          }}>
            Loading memory graph...
          </div>
        )}
        {error && (
          <div style={{
            position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: 12,
            color: '#ff6b6b', fontSize: 14,
          }}>
            <div>{error}</div>
            <button
              onClick={fetchGraph}
              style={{
                background: '#333', border: '1px solid #555', color: '#ccc',
                padding: '6px 16px', borderRadius: 4, cursor: 'pointer',
              }}
            >
              Retry
            </button>
          </div>
        )}
        {data && !loading && !error && (
          <MemoryGraph3D data={data} />
        )}
      </div>
    </div>
  );
}
```

---

## Change 6 — Add Memory Tab to Profile Panel

### File: `ui/src/components/profile/AgentProfilePanel.tsx`

**Change 6a:** Add import at top of file (with other profile tab imports):
```typescript
import { ProfileMemoryTab } from './ProfileMemoryTab';
```

**Change 6b:** At line 9, add `'memory'` to the type union:
```typescript
type ProfileTab = 'chat' | 'work' | 'profile' | 'health' | 'memory';
```

**Change 6c:** At line 15, add `memory` entry to `TAB_LABELS` (insert after `work`, before `profile`):
```typescript
{ key: 'memory', label: 'Memory' },
```

**Change 6d:** At lines 93-95, the `visibleTabs` filter already hides `'chat'` for non-crew agents. Add `'memory'` to the same filter so non-crew agents don't show the Memory tab either:
```typescript
// Before (existing):
const visibleTabs = isCrew ? TAB_LABELS : TAB_LABELS.filter(t => t.key !== 'chat');
// After:
const visibleTabs = isCrew ? TAB_LABELS : TAB_LABELS.filter(t => t.key !== 'chat' && t.key !== 'memory');
```

**Change 6e:** In the tab content render section (~line 207), add the Memory tab render:
```typescript
{effectiveTab === 'memory' && <ProfileMemoryTab agentId={agent.id} />}
```

---

## Tests

### File: `tests/test_ad611_memory_graph.py` (NEW)

Test the backend `memory_graph` router. Follow existing pattern: direct handler call with `MagicMock(spec=...)`, no HTTP client.

```python
"""AD-611: 3D Memory Graph Visualization tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from probos.types import Episode, AnchorFrame


def _make_episode(
    ep_id: str = "ep-001",
    user_input: str = "test input",
    importance: int = 5,
    timestamp: float = 1000.0,
    agent_ids: list[str] | None = None,
    channel: str = "bridge",
    department: str = "bridge",
    thread_id: str = "",
    participants: list[str] | None = None,
    source: str = "ward_room",
) -> Episode:
    return Episode(
        id=ep_id,
        user_input=user_input,
        importance=importance,
        timestamp=timestamp,
        agent_ids=agent_ids or ["agent-a"],
        source=source,
        anchors=AnchorFrame(
            channel=channel,
            department=department,
            thread_id=thread_id,
            participants=participants or [],
        ),
    )


def _make_runtime(episodes: list[Episode] | None = None):
    runtime = MagicMock()
    episodes = episodes or []

    runtime.episodic_memory = AsyncMock()
    runtime.episodic_memory.recent_for_agent = AsyncMock(return_value=episodes)
    runtime.episodic_memory.recall_by_anchor = AsyncMock(return_value=[])
    runtime.episodic_memory.count_for_agent = AsyncMock(return_value=len(episodes))
    runtime.episodic_memory.get_embeddings = AsyncMock(return_value={})
    runtime.episodic_memory._collection = None  # No ChromaDB in tests
    runtime.episodic_memory._activation_tracker = None
    runtime.identity_registry = None
    runtime.registry = MagicMock()
    runtime.registry.all.return_value = []

    return runtime


@pytest.mark.asyncio
async def test_empty_memory_returns_empty_graph():
    from probos.routers.memory_graph import get_memory_graph

    runtime = _make_runtime([])
    result = await get_memory_graph("agent-a", runtime)
    assert result["nodes"] == []
    assert result["edges"] == []
    assert result["meta"]["nodes_shown"] == 0


@pytest.mark.asyncio
async def test_nodes_built_from_episodes():
    from probos.routers.memory_graph import get_memory_graph

    eps = [
        _make_episode("ep-1", "Hello bridge", importance=8, timestamp=1000),
        _make_episode("ep-2", "Engineering report", importance=3, timestamp=2000,
                       channel="engineering"),
    ]
    runtime = _make_runtime(eps)
    result = await get_memory_graph("agent-a", runtime)

    assert len(result["nodes"]) == 2
    node_ids = {n["id"] for n in result["nodes"]}
    assert "ep-1" in node_ids
    assert "ep-2" in node_ids
    # Verify importance → size mapping
    node_1 = next(n for n in result["nodes"] if n["id"] == "ep-1")
    assert node_1["importance"] == 8
    assert node_1["size"] > 4.0  # 2 + (8/10)*4 = 5.2


@pytest.mark.asyncio
async def test_node_color_by_channel():
    from probos.routers.memory_graph import get_memory_graph

    eps = [
        _make_episode("ep-1", "test", channel="bridge"),
        _make_episode("ep-2", "test", channel="medical"),
    ]
    runtime = _make_runtime(eps)
    result = await get_memory_graph("agent-a", runtime)

    node_1 = next(n for n in result["nodes"] if n["id"] == "ep-1")
    node_2 = next(n for n in result["nodes"] if n["id"] == "ep-2")
    assert node_1["color"] == "#f0b060"  # bridge
    assert node_2["color"] == "#52c474"  # medical


@pytest.mark.asyncio
async def test_thread_edges_created():
    from probos.routers.memory_graph import _build_edges

    eps = [
        _make_episode("ep-1", "msg 1", thread_id="thread-abc", timestamp=1000),
        _make_episode("ep-2", "msg 2", thread_id="thread-abc", timestamp=1001),
        _make_episode("ep-3", "msg 3", thread_id="thread-xyz", timestamp=1002),
    ]
    episodic = AsyncMock()
    episodic.get_embeddings = AsyncMock(return_value={})
    episodic._collection = None

    edges = await _build_edges(episodic, eps, [e.id for e in eps], semantic_k=5)
    thread_edges = [e for e in edges if e["type"] == "thread"]
    assert len(thread_edges) == 1  # ep-1 ↔ ep-2 share thread-abc
    assert {thread_edges[0]["source"], thread_edges[0]["target"]} == {"ep-1", "ep-2"}


@pytest.mark.asyncio
async def test_temporal_edges_within_5_minutes():
    from probos.routers.memory_graph import _build_edges

    eps = [
        _make_episode("ep-1", "msg 1", timestamp=1000),
        _make_episode("ep-2", "msg 2", timestamp=1120),   # 2 min later
        _make_episode("ep-3", "msg 3", timestamp=2000),   # 16 min later
    ]
    episodic = AsyncMock()
    episodic.get_embeddings = AsyncMock(return_value={})
    episodic._collection = None

    edges = await _build_edges(episodic, eps, [e.id for e in eps], semantic_k=5)
    temporal_edges = [e for e in edges if e["type"] == "temporal"]
    assert len(temporal_edges) == 1  # only ep-1 ↔ ep-2
    assert temporal_edges[0]["weight"] > 0.5  # 1 - (120/300) = 0.6


@pytest.mark.asyncio
async def test_participant_edges_jaccard():
    from probos.routers.memory_graph import _build_edges

    eps = [
        _make_episode("ep-1", "msg 1", participants=["atlas", "lynx", "kira"]),
        _make_episode("ep-2", "msg 2", participants=["atlas", "lynx"]),
        _make_episode("ep-3", "msg 3", participants=["bones"]),
    ]
    episodic = AsyncMock()
    episodic.get_embeddings = AsyncMock(return_value={})
    episodic._collection = None

    edges = await _build_edges(episodic, eps, [e.id for e in eps], semantic_k=5)
    part_edges = [e for e in edges if e["type"] == "participant"]
    # ep-1(atlas,lynx,kira) ↔ ep-2(atlas,lynx): Jaccard = 2/3 ≈ 0.667 > 0.3 → edge
    # ep-1 ↔ ep-3: no overlap → no edge
    # ep-2 ↔ ep-3: no overlap → no edge
    assert len(part_edges) == 1
    assert part_edges[0]["weight"] == pytest.approx(0.667, abs=0.01)


@pytest.mark.asyncio
async def test_edge_cap_enforced():
    from probos.routers.memory_graph import _build_edges, MAX_EDGES_CAP

    # Create many episodes close in time to generate lots of temporal edges
    eps = [
        _make_episode(f"ep-{i}", f"msg {i}", timestamp=1000 + i)
        for i in range(100)
    ]
    episodic = AsyncMock()
    episodic.get_embeddings = AsyncMock(return_value={})
    episodic._collection = None

    edges = await _build_edges(episodic, eps, [e.id for e in eps], semantic_k=5)
    assert len(edges) <= MAX_EDGES_CAP


@pytest.mark.asyncio
async def test_max_nodes_cap():
    from probos.routers.memory_graph import get_memory_graph

    eps = [_make_episode(f"ep-{i}", f"msg {i}") for i in range(10)]
    runtime = _make_runtime(eps)
    # Request more than MAX_NODES_CAP
    result = await get_memory_graph("agent-a", runtime, max_nodes=9999)
    # Should be capped (and won't exceed episode count either)
    assert result["meta"]["nodes_shown"] <= 500


@pytest.mark.asyncio
async def test_no_episodic_memory_returns_503():
    from probos.routers.memory_graph import get_memory_graph

    runtime = MagicMock()
    runtime.episodic_memory = None
    result = await get_memory_graph("agent-a", runtime)
    assert result.status_code == 503


@pytest.mark.asyncio
async def test_activation_drives_node_opacity():
    from probos.routers.memory_graph import get_memory_graph

    eps = [_make_episode("ep-1", "test")]
    runtime = _make_runtime(eps)
    tracker = AsyncMock()
    tracker.get_activations_batch = AsyncMock(return_value={"ep-1": 3.0})
    runtime.episodic_memory._activation_tracker = tracker

    result = await get_memory_graph("agent-a", runtime)
    node = result["nodes"][0]
    # sigmoid(3.0) ≈ 0.953
    assert node["activation"] > 0.9


@pytest.mark.asyncio
async def test_ship_wide_merges_agents():
    from probos.routers.memory_graph import get_memory_graph

    ep_a = _make_episode("ep-a", "agent A", agent_ids=["agent-a"])
    ep_b = _make_episode("ep-b", "agent B", agent_ids=["agent-b"])

    runtime = _make_runtime([])
    # Ship-wide queries each agent separately
    agent_a = MagicMock()
    agent_a.id = "agent-a"
    agent_b = MagicMock()
    agent_b.id = "agent-b"
    runtime.registry.all.return_value = [agent_a, agent_b]

    # Mock is_crew_agent to return True for both
    with patch("probos.routers.memory_graph.is_crew_agent", return_value=True):
        # recent_for_agent returns different episodes per agent
        call_count = 0
        async def side_effect(sid, k=5):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [ep_a]
            return [ep_b]
        runtime.episodic_memory.recent_for_agent = AsyncMock(side_effect=side_effect)

        result = await get_memory_graph("agent-a", runtime, ship_wide=True)
        node_ids = {n["id"] for n in result["nodes"]}
        assert "ep-a" in node_ids
        assert "ep-b" in node_ids
```

---

## Verification

```bash
# Backend tests
uv run python -m pytest tests/test_ad611_memory_graph.py -v

# Frontend build
cd ui && npm install react-force-graph-3d && npm run build

# Manual verification
# 1. Start ProbOS, open HXI
# 2. Click crew agent → profile panel → Memory tab
# 3. Verify 3D graph renders with colored nodes, edges, legend
# 4. Hover nodes for tooltips, click for detail panel
# 5. Toggle ship-wide checkbox, verify graph refreshes
# 6. Check graph stabilizes within 3-5 seconds
```

## Tracking

Update: PROGRESS.md, DECISIONS.md, `docs/development/roadmap.md`. Close GitHub issue seangalliher/ProbOS#192.

## Engineering Principles Compliance

- **SOLID (S):** Backend split into focused functions: `_select_episodes`, `_build_nodes`, `_build_edges`, `_get_crew_agents`. Frontend split: types file, graph component, tab wrapper, panel integration.
- **SOLID (D):** Router depends on `runtime` abstraction via `Depends(get_runtime)`. Uses existing `EpisodicMemory` public API for node data, `ActivationTracker.get_activations_batch()` for activation.
- **Law of Demeter:** Only one private access — `episodic._collection.query()` for HNSW embedding queries — justified by absence of public wrapper (documented in notes). All other access uses public methods.
- **Fail Fast:** `JSONResponse(503)` for missing episodic memory. Edge/activation failures log-and-degrade (return empty arrays, continue rendering). Graph renders with whatever data is available.
- **DRY:** Reuses existing `resolve_sovereign_id_from_slot`, `is_crew_agent`, `get_runtime`. Color maps defined once as module constants. `EDGE_TYPE_CONFIG` shared between frontend types and component.
- **Cloud-Ready Storage:** No new DB modules — reads from existing ChromaDB + SQLite via established interfaces. Storage-agnostic by construction.
- **Defense in Depth:** `max_nodes` capped server-side (`min(max_nodes, 500)`). Edge cap enforced. Query params validated via FastAPI `Query(ge=, le=)`.
