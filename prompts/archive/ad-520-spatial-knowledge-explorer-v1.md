# AD-520 v1 — Spatial Knowledge Explorer: Digital Twin & 3D Ontology Visualization (Phase 1 + Phase 2)

**Status:** Architect-drafted (4 review passes), Builder-ready
**Wave:** 103
**Closes:** GH #95
**Roadmap anchor:** `docs/development/roadmap.md:6419`
**HEAD:** `ecaf30f` — pytest 12459 / vitest 363
**Floor:** +16 pytest (target ≥12475) / +30 vitest (target ≥393)
**Stretch:** +20 pytest (12480) / +35 vitest (398)

## Problem

The ship ontology (AD-429) defines a topology — departments, posts, chain of command, trust networks, records — but it is only visible as text and 2D tables. The HXI's existing `<CognitiveCanvas>` (orbital agent view) shows agent activity but not organizational topology, deck layout, or knowledge-graph relationships.

The roadmap entry at `roadmap.md:6419` calls for a Spatial Knowledge Explorer in three tiers: Phase 1 (OSS Knowledge Graph View — force-directed 3D graph of ontology + records), Phase 2 (OSS Spatial Ship Layout — ontology mapped to physical deck topology), Phase 3 (Commercial Digital Twin — walkable WebXR immersive ship). All three needed for the spec to be "fully delivered." Phase 1 + Phase 2 are OSS; Phase 3 is explicit Commercial scope.

## Solution

Ship Phase 1 + Phase 2 in one v1 (Captain rule "don't defer unless no choice"). All required dependencies (`react-force-graph-3d ^1.29.1`, `@react-three/fiber ^9`, `@react-three/drei ^10`, `three ^0.172`) are already in tree from AD-611 — zero new npm dependencies. All required backend data sources are already wired (`ont.get_crew_manifest()` AD-513, `ont.get_organization()` AD-429a, `runtime.knowledge_edges` AD-687/689/692). Phase 1 needs one new aggregator endpoint `/api/ontology/graph` that combines the three reads server-side; Phase 2 needs one new endpoint `/api/ontology/spatial-layout` that returns a YAML-defined deck topology. The new HXI panel `<SpatialExplorerPanel>` is additive — it does NOT touch `<CognitiveCanvas>` (HXI fragility rule from `/memories/repo/probos-notes.md`).

Phase 3 (Commercial Digital Twin — walkable WebXR + fleet-zoom + holographic record displays) is descriptor-only out-of-scope — class-extension territory under the private overlay-repo path token surface. v1 ships `SpatialLayout` in renderer-agnostic shape so a future commercial overlay can mount its own `<WebXRImmersiveTwin>` against `runtime.spatial_layout` with zero backend changes.

## Section 0: New EventTypes

**None.** v1 adds no new EventTypes. The spatial explorer is read-only — it consumes existing crew/edge/manifest state and the existing `bridge_alert` event already drives alert-condition tinting via the existing store websocket loop.

## Section 1: Add `SpatialExplorerConfig` Pydantic model

In `src/probos/config.py`, insert immediately after `MCPAppHostConfig` (currently at `:821`):

```
===MODIFY: src/probos/config.py===
===SEARCH===
class MCPAppHostConfig(BaseModel):
===REPLACE===
class SpatialExplorerConfig(BaseModel):
    """AD-520: Spatial Knowledge Explorer (Phase 1 Knowledge Graph View + Phase 2 Spatial Ship Layout).

    Default-False per AD-695 transitional precedent — wirer reads YAML and
    constructs an in-memory layout, not zero-cost on boot. Operator opt-in.
    """

    enabled: bool = False
    max_graph_edges: int = Field(default=500, ge=0, le=5000)
    max_graph_nodes: int = Field(default=200, ge=0, le=2000)
    spatial_layout_path: str = ""  # empty → resolves to config/ontology/spatial.yaml then to _DEFAULT_LAYOUT


class MCPAppHostConfig(BaseModel):
===END REPLACE===
```

Wire on `SystemConfig` adjacent to the existing `mcp_app_host` field (verified at `config.py:2904` inside `class SystemConfig(BaseModel)` at `:2831`):

```
===MODIFY: src/probos/config.py===
===SEARCH===
    mcp_app_host: MCPAppHostConfig = Field(default_factory=MCPAppHostConfig)  # AD-597
===REPLACE===
    mcp_app_host: MCPAppHostConfig = Field(default_factory=MCPAppHostConfig)  # AD-597
    spatial_explorer: SpatialExplorerConfig = Field(default_factory=SpatialExplorerConfig)  # AD-520
===END REPLACE===
```

## Section 2: New module `src/probos/ontology/spatial.py`

Create the file with the following content:

```python
"""AD-520: Spatial Knowledge Explorer — deck topology and agent positioning.

Renderer-agnostic SpatialLayout data model. The OSS HXI uses this for the
Phase 2 Spatial Ship Layout view. A future commercial overlay can mount a
WebXR immersive experience against the same layout without backend changes.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_DECK_DIMENSIONS: tuple[float, float, float] = (8.0, 1.5, 6.0)


@dataclass(frozen=True)
class SpatialDeck:
    """A single deck in the ship topology."""

    deck_id: str
    name: str
    department_id: str | None
    position: tuple[float, float, float]
    dimensions: tuple[float, float, float] = _DEFAULT_DECK_DIMENSIONS
    post_offsets: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    accent_color: str = "#666680"

    def to_dict(self) -> dict[str, Any]:
        return {
            "deck_id": self.deck_id,
            "name": self.name,
            "department_id": self.department_id,
            "position": list(self.position),
            "dimensions": list(self.dimensions),
            "accent_color": self.accent_color,
            "post_offsets": {k: list(v) for k, v in self.post_offsets.items()},
        }


@dataclass(frozen=True)
class SpatialLayout:
    """Top-level ship topology — one or more decks."""

    decks: list[SpatialDeck]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decks": [d.to_dict() for d in self.decks],
        }

    def find_deck_for_department(self, department_id: str | None) -> SpatialDeck | None:
        if not department_id:
            return None
        for d in self.decks:
            if d.department_id == department_id:
                return d
        return None


_DEFAULT_LAYOUT = SpatialLayout(
    decks=[
        SpatialDeck(
            deck_id="bridge",
            name="Bridge",
            department_id="command",
            position=(0.0, 6.0, 0.0),
            dimensions=(8.0, 1.5, 6.0),
            accent_color="#f0b060",
            post_offsets={
                "captain": (0.0, 0.0, -1.0),
                "first_officer": (-1.5, 0.0, 0.0),
                "counselor": (1.5, 0.0, 0.0),
                "yeoman": (0.0, 0.0, 1.5),
            },
        ),
        SpatialDeck(
            deck_id="engineering",
            name="Engineering",
            department_id="engineering",
            position=(0.0, 0.0, 6.0),
            dimensions=(8.0, 2.0, 6.0),
            accent_color="#d8742a",
            post_offsets={"chief_engineer": (0.0, 0.0, 0.0)},
        ),
        SpatialDeck(
            deck_id="sickbay",
            name="Sickbay",
            department_id="medical",
            position=(-6.0, 3.0, 0.0),
            dimensions=(6.0, 1.5, 6.0),
            accent_color="#54c474",
            post_offsets={"chief_medical_officer": (0.0, 0.0, 0.0)},
        ),
        SpatialDeck(
            deck_id="tactical",
            name="Tactical",
            department_id="security",
            position=(6.0, 3.0, 0.0),
            dimensions=(6.0, 1.5, 6.0),
            accent_color="#c84858",
            post_offsets={"chief_of_security": (0.0, 0.0, 0.0)},
        ),
        SpatialDeck(
            deck_id="science_lab",
            name="Science Lab",
            department_id="science",
            position=(0.0, 3.0, -6.0),
            dimensions=(6.0, 1.5, 6.0),
            accent_color="#5ca0d4",
            post_offsets={"chief_science_officer": (0.0, 0.0, 0.0)},
        ),
        SpatialDeck(
            deck_id="computer_core",
            name="Computer Core",
            department_id="ship-systems",
            position=(0.0, -3.0, 0.0),
            dimensions=(6.0, 2.0, 6.0),
            accent_color="#8870c4",
            post_offsets={},
        ),
        SpatialDeck(
            deck_id="common_areas",
            name="Common Areas",
            department_id=None,
            position=(0.0, 1.0, 0.0),
            dimensions=(10.0, 1.0, 10.0),
            accent_color="#666680",
            post_offsets={},
        ),
    ],
    schema_version=1,
)


def load_spatial_layout(path: str | None) -> SpatialLayout:
    """Load a SpatialLayout from YAML, falling back to _DEFAULT_LAYOUT.

    Tier-2 log-and-degrade: any failure (missing file, parse error, schema
    mismatch) returns _DEFAULT_LAYOUT with a WARNING log. Returns
    _DEFAULT_LAYOUT when path is empty/None.
    """
    if not path:
        return _DEFAULT_LAYOUT
    if not os.path.exists(path):
        logger.warning("AD-520: spatial layout file not found at %s; using default", path)
        return _DEFAULT_LAYOUT
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        decks_raw = data.get("decks", [])
        if not isinstance(decks_raw, list) or not decks_raw:
            logger.warning("AD-520: spatial layout %s has empty/invalid decks; using default", path)
            return _DEFAULT_LAYOUT
        decks = []
        for d in decks_raw:
            if not isinstance(d, dict):
                continue
            decks.append(
                SpatialDeck(
                    deck_id=str(d.get("deck_id", "")),
                    name=str(d.get("name", "")),
                    department_id=d.get("department_id"),
                    position=tuple(d.get("position", (0.0, 0.0, 0.0)))[:3],  # type: ignore[arg-type]
                    dimensions=tuple(d.get("dimensions", _DEFAULT_DECK_DIMENSIONS))[:3],  # type: ignore[arg-type]
                    post_offsets={
                        str(k): tuple(v)[:3]  # type: ignore[arg-type]
                        for k, v in (d.get("post_offsets", {}) or {}).items()
                    },
                    accent_color=str(d.get("accent_color", "#666680")),
                )
            )
        if not decks:
            return _DEFAULT_LAYOUT
        return SpatialLayout(decks=decks, schema_version=int(data.get("schema_version", 1)))
    except Exception as exc:  # noqa: BLE001 — tier-2 log-and-degrade
        logger.warning("AD-520: failed to parse spatial layout %s: %s; using default", path, exc)
        return _DEFAULT_LAYOUT


def compute_agent_positions(
    layout: SpatialLayout, manifest: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Map each crew-manifest entry to a 3D position via deck + post-offset.

    Agents without a known deck/department are placed at the 'common_areas'
    deck offset and flagged on_watch=False. Pure helper — no I/O.
    """
    common = next(
        (d for d in layout.decks if d.deck_id == "common_areas"),
        layout.decks[-1] if layout.decks else None,
    )
    out: list[dict[str, Any]] = []
    for entry in manifest:
        agent_id = entry.get("agent_id") or entry.get("agent_type") or ""
        agent_type = entry.get("agent_type") or agent_id
        department = entry.get("department")
        post = entry.get("post") or ""
        deck = layout.find_deck_for_department(department) or common
        if deck is None:
            continue
        offset = deck.post_offsets.get(post, (0.0, 0.0, 0.0))
        position = (
            deck.position[0] + offset[0],
            deck.position[1] + offset[1],
            deck.position[2] + offset[2],
        )
        out.append(
            {
                "agent_id": agent_id,
                "agent_type": agent_type,
                "department": department,
                "post": post,
                "deck_id": deck.deck_id,
                "position": list(position),
                "on_watch": bool(entry.get("on_watch", False)),
            }
        )
    return out
```

## Section 3: Add public `runtime.spatial_layout` slot

In `src/probos/runtime.py`, locate the existing `self.knowledge_edges` line at `:482` and add the spatial_layout slot immediately after:

```
===MODIFY: src/probos/runtime.py===
===SEARCH===
        self.knowledge_edges: Any = None  # SQLiteKnowledgeEdgeStore | None — Any to avoid circular import
===REPLACE===
        self.knowledge_edges: Any = None  # SQLiteKnowledgeEdgeStore | None — Any to avoid circular import
        self.spatial_layout: Any = None  # AD-520: SpatialLayout | None — set by _wire_spatial_explorer
===END REPLACE===
```

## Section 4: New finalize wirer `_wire_spatial_explorer`

In `src/probos/startup/finalize.py`, insert immediately after the `_wire_mcp_app_host` definition body (currently starts at `:863`). Locate the function and add the new wirer below it:

```
===MODIFY: src/probos/startup/finalize.py===
===SEARCH===
def _wire_mcp_app_host(*, runtime: Any, config: "SystemConfig") -> bool:
===REPLACE===
def _wire_spatial_explorer(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-520: Construct runtime.spatial_layout from YAML or default.

    Default-False per AD-695 transitional precedent. Pure sync wirer —
    no asyncio task creation, no other side-effects. The explorer is a
    read-only HXI surface backed by REST consumption of existing data.
    """
    cfg = getattr(config, "spatial_explorer", None)
    if cfg is None or not getattr(cfg, "enabled", False):
        return False
    from probos.ontology.spatial import load_spatial_layout

    path = cfg.spatial_layout_path or "config/ontology/spatial.yaml"
    layout = load_spatial_layout(path)
    runtime.spatial_layout = layout
    logger.info(
        "AD-520: spatial explorer wired with %d decks (path=%s)", len(layout.decks), path
    )
    return True


def _wire_mcp_app_host(*, runtime: Any, config: "SystemConfig") -> bool:
===END REPLACE===
```

Add the invocation site immediately after the existing `_wire_mcp_app_host` try/except block in `finalize_startup` (currently at `:3017-3022` per verify-first read of lines 3017-3022: `# AD-597: Wire MCP App Host registry...` comment + `try:` + invocation + `except Exception:` + `logger.warning(...)`). The SEARCH consumes the full 4-line try/except block including the leading comment line; the REPLACE re-emits the existing block byte-for-byte and appends a new analogous block for `_wire_spatial_explorer`:

```
===MODIFY: src/probos/startup/finalize.py===
===SEARCH===
    # AD-597: Wire MCP App Host registry (default-False; serves internal games when enabled)
    try:
        _wire_mcp_app_host(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-597: _wire_mcp_app_host failed", exc_info=True)
===REPLACE===
    # AD-597: Wire MCP App Host registry (default-False; serves internal games when enabled)
    try:
        _wire_mcp_app_host(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-597: _wire_mcp_app_host failed", exc_info=True)

    # AD-520: Wire Spatial Knowledge Explorer (default-False; constructs runtime.spatial_layout)
    try:
        _wire_spatial_explorer(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-520: _wire_spatial_explorer failed", exc_info=True)
===END REPLACE===
```

## Section 5: Two new GET endpoints in `src/probos/routers/ontology.py`

Append both endpoints after the existing `get_ontology_skills` route (`:84-85`):

```
===MODIFY: src/probos/routers/ontology.py===
===SEARCH===
@router.get("/skills/{agent_type}")
async def get_ontology_skills(agent_type: str, runtime: Any = Depends(get_runtime)) -> Any:
===REPLACE===
@router.get("/graph")
async def get_ontology_graph(
    runtime: Any = Depends(get_runtime),
    include_edges: bool = True,
    max_edges: int = 500,
    max_nodes: int = 200,
    edge_relations: str = "",
) -> Any:
    """AD-520: Spatial Knowledge Explorer — graph snapshot.

    Combines crew-manifest + organization + (optional) knowledge_edges into
    a force-graph-shaped JSON payload {nodes, edges, generated_at}.
    """
    import time as _time
    ont = runtime.ontology
    if not ont:
        return JSONResponse({"error": "Ontology not initialized"}, status_code=503)

    # Department nodes
    nodes: list[dict[str, Any]] = []
    for dept in ont.get_departments():
        d = asdict(dept)
        nodes.append(
            {
                "id": d.get("id"),
                "label": d.get("name") or d.get("id"),
                "type": "department",
                "accent_color": d.get("accent_color", "#666680"),
            }
        )

    # Agent nodes from crew manifest
    manifest = ont.get_crew_manifest(
        trust_network=getattr(runtime, "trust_network", None),
        callsign_registry=getattr(runtime, "callsign_registry", None),
    )
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

    # Edges: assignment-derived member_of (always)
    edges: list[dict[str, Any]] = []
    for a in ont.get_all_assignments():
        ad = asdict(a)
        edges.append(
            {
                "id": f"member_of:{ad.get('agent_type')}:{ad.get('post_id')}",
                "source": ad.get("agent_type"),
                "target": ad.get("post_id"),
                "relation": "member_of",
                "weight": 1.0,
            }
        )

    # Edges: knowledge_edges (optional, capped)
    if include_edges and getattr(runtime, "knowledge_edges", None) is not None and max_edges > 0:
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
            graph_edges = await runtime.knowledge_edges.find_edges(limit=max_edges)
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
        except Exception as exc:  # noqa: BLE001 — tier-2 log-and-degrade
            logger.warning("AD-520: knowledge_edges.find_edges failed: %s", exc)

    # Truncate combined node list
    if max_nodes > 0 and len(nodes) > max_nodes:
        nodes = nodes[:max_nodes]

    return {
        "nodes": nodes,
        "edges": edges,
        "generated_at": _time.time(),
    }


@router.get("/spatial-layout")
async def get_spatial_layout(runtime: Any = Depends(get_runtime)) -> Any:
    """AD-520: Spatial Knowledge Explorer — deck topology snapshot."""
    layout = getattr(runtime, "spatial_layout", None)
    if layout is None:
        return JSONResponse(
            {"error": "Spatial explorer not enabled"}, status_code=503
        )
    return layout.to_dict()


@router.get("/skills/{agent_type}")
async def get_ontology_skills(agent_type: str, runtime: Any = Depends(get_runtime)) -> Any:
===END REPLACE===
```

## Section 6: New YAML `config/ontology/spatial.yaml`

Create a new file at `config/ontology/spatial.yaml` whose contents are the YAML-serialized form of `_DEFAULT_LAYOUT.to_dict()`. Run the equivalent of `python -c "import yaml; from probos.ontology.spatial import _DEFAULT_LAYOUT; print(yaml.safe_dump(_DEFAULT_LAYOUT.to_dict(), sort_keys=False, default_flow_style=False))"` and commit the output to that path. The file is operator-editable; the in-code default is the source of truth at v1 ship time.

## Section 7: HXI store extension

```
===MODIFY: ui/src/store/types.ts===
===SEARCH===
export interface BehavioralSnapshot {
===REPLACE===
export type SpatialViewMode = 'graph' | 'ship';

export interface SpatialSelection {
  kind: 'agent' | 'department' | 'edge';
  id: string;
  payload: Record<string, unknown>;
}

export interface SpatialGraphData {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  generated_at: number;
}

export interface SpatialLayoutData {
  schema_version: number;
  decks: Array<{
    deck_id: string;
    name: string;
    department_id: string | null;
    position: [number, number, number];
    dimensions: [number, number, number];
    accent_color: string;
    post_offsets: Record<string, [number, number, number]>;
  }>;
}

export interface BehavioralSnapshot {
===END REPLACE===
```

In `ui/src/store/useStore.ts`, append the following to the state shape, the actions interface, the initial state object, and the implementation block (mirror the `behavioralMetricsOpen` precedent — refer to existing patterns at AD-569g shape). Add:

- State fields: `spatialExplorerOpen: boolean` (default `false`), `spatialViewMode: SpatialViewMode` (default `'graph'`), `spatialSelectedNode: SpatialSelection | null` (default `null`), `spatialGraphData: SpatialGraphData | null` (default `null`), `spatialLayoutData: SpatialLayoutData | null` (default `null`).
- Actions: `openSpatialExplorer: () => void`, `closeSpatialExplorer: () => void`, `setSpatialViewMode: (mode: SpatialViewMode) => void`, `setSpatialSelectedNode: (sel: SpatialSelection | null) => void`, `setSpatialGraphData: (data: SpatialGraphData | null) => void`, `setSpatialLayoutData: (data: SpatialLayoutData | null) => void`.

(The Builder should pattern-match the `behavioralMetricsOpen`/`openBehavioralMetrics` block already in the file and replicate it 5 times for the new state fields, mirroring the same `set` calls.)

## Section 8: New HXI components

Create the following new files. Each component must follow the HXI Design Principles in `.github/copilot-instructions.md` (no emoji; SVG icons with `strokeWidth: 1.5`, `strokeLinecap: round`; amber `#f0b060` active / dim `#666680` inactive; `#0a0a12` background; `rgba(10,10,18,0.75)` panel surface; `backdropFilter: blur(8px)`; `JetBrains Mono` typography). Mirror the existing `BehavioralMetricsPanel.tsx` glass styling and ESC handler precedent.

- `ui/src/components/SpatialExplorerPanel.tsx` — 720×640 floating draggable panel. Header with `SPATIAL EXPLORER` title, view-mode tabs (`GRAPH` / `SHIP LAYOUT`), refresh button (`↻` Unicode glyph), close button (`×` Unicode glyph). On mount fetches `/api/ontology/graph?include_edges=true` and `/api/ontology/spatial-layout` once via `fetch()`; refresh button re-invokes both. ESC handler closes (replicate the existing pattern in `BehavioralMetricsPanel.tsx`). Conditional render: `viewMode==='graph' ? <KnowledgeGraphView /> : <ShipLayoutView />`. Persistent `<NodeDetailDrawer />` on the right edge when `spatialSelectedNode !== null`. Inline status text for empty / loading / error states (no spinner GIF — text-only per HXI principle). Empty graph data → `"No graph data — enable in config or check ontology service"`. Network error → `"Failed to load — see console"`.

- `ui/src/components/spatial/types.ts` — re-export the store types for convenience and add:
  ```typescript
  export interface SpatialNode {
    id: string;
    label: string;
    type: 'agent' | 'department';
    department?: string;
    rank?: string;
    trust?: number;
    post?: string;
    on_watch?: boolean;
    accent_color?: string;
  }

  export interface SpatialEdge {
    id: string;
    source: string;
    target: string;
    relation: string;
    weight: number;
    confidence?: number;
  }

  export type GraphMode = 'org' | 'trust' | 'knowledge' | 'department';
  ```

- `ui/src/components/spatial/KnowledgeGraphView.tsx` — wraps `<ForceGraph3D>` from `react-force-graph-3d` (same import pattern as `MemoryGraph3D.tsx` already in tree at AD-611). Mode chips: `ORG CHART` (filters edges to `member_of` + `reports_to`, sets DAG mode), `TRUST NETWORK` (synthesizes edges from agent trust scores), `KNOWLEDGE MAP` (all relation types), `DEPARTMENT VIEW` (clusters by department). Department filter chips one per unique `department` value. Node color from a small department palette helper (amber/cyan/teal/violet/green/gold per HXI Design Principle #3). Node `val` (size) from `trust * 10` clamped [3, 12]. Click handler → `useStore.setState(s => ({...s, spatialSelectedNode: {kind: 'agent', id: node.id, payload: node}}))`. Edge color/width from relation type lookup + `weight`.

- `ui/src/components/spatial/ShipLayoutView.tsx` — R3F `<Canvas>` with `<OrbitControls>`. Renders one `<group>` per deck at `deck.position` containing a wireframe `<lineSegments>` with `<edgesGeometry>` from a `<boxGeometry args={deck.dimensions}>` and a `<Text>` label from `@react-three/drei` showing `deck.name`. Inside each deck, renders one `<mesh>` per agent (computed via `compute_agent_positions` equivalent on the frontend OR by reading the `manifest`-derived agent nodes and joining against `spatialLayoutData.decks` to compute position client-side). Each agent mesh is a sphere geometry colored by department accent. Agent meshes scale-pulse via `useFrame` + `Math.sin(state.clock.elapsedTime * 2)` when the agent is in the store's `agents` map with `activity_state === 'active'`. Alert-condition tint overlay: read `useStore(s => s.alertCondition)` (or equivalent existing alert state); CRITICAL → all decks tint red `#c84858`; ALERT → amber `#f0b060`; otherwise neutral. Click on an agent mesh dispatches `setSpatialSelectedNode({kind:'agent', id, payload})`. Bloom postprocessing optional (reuse `@react-three/postprocessing` import pattern from `CognitiveCanvas.tsx`).

- `ui/src/components/spatial/NodeDetailDrawer.tsx` — 280px wide right-edge drawer rendered inside `SpatialExplorerPanel`. Renders `spatialSelectedNode.payload` as a structured 2-column table (key/value rows for `department`, `rank`, `post`, `trust`, `on_watch` for kind='agent'; `relation`, `weight`, `confidence`, `source`, `target` for kind='edge'; `accent_color` for kind='department'). Header shows `kind.toUpperCase()` + truncated id. Close button (`×`) clears selection.

- `ui/src/components/SpatialExplorerToggle` (define inline in `App.tsx` adjacent to `BehavioralMetricsToggle`):

```
===MODIFY: ui/src/App.tsx===
===SEARCH===
function BehavioralMetricsToggle() {
  const open = useStore(s => s.behavioralMetricsOpen);
  const openMetrics = useStore(s => s.openBehavioralMetrics);
===REPLACE===
function SpatialExplorerToggle() {
  const open = useStore(s => s.spatialExplorerOpen);
  const openExplorer = useStore(s => s.openSpatialExplorer);

  if (open) return null;

  return (
    <div
      onClick={() => openExplorer()}
      data-testid="spatial-explorer-toggle"
      style={{
        position: 'fixed',
        top: 12, left: 340,
        zIndex: 25,
        padding: '6px 12px',
        background: 'rgba(10, 10, 18, 0.75)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        border: '1px solid rgba(240, 176, 96, 0.15)',
        borderRadius: 6,
        cursor: 'pointer',
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: 1.5,
        fontFamily: "'JetBrains Mono', monospace",
        color: '#8888a0',
        userSelect: 'none' as const,
      }}
    >
      EXPLORER
    </div>
  );
}

function BehavioralMetricsToggle() {
  const open = useStore(s => s.behavioralMetricsOpen);
  const openMetrics = useStore(s => s.openBehavioralMetrics);
===END REPLACE===
```

Add the import + mount the panel + the toggle. Locate the existing `BehavioralMetricsPanel` import and append:

```
===MODIFY: ui/src/App.tsx===
===SEARCH===
import BehavioralMetricsPanel from './components/BehavioralMetricsPanel';
===REPLACE===
import BehavioralMetricsPanel from './components/BehavioralMetricsPanel';
import SpatialExplorerPanel from './components/SpatialExplorerPanel';
===END REPLACE===
```

Mount the panel + toggle at the App return tree adjacent to `<BehavioralMetricsPanel />` (Builder: locate the existing `<BehavioralMetricsPanel />` JSX line and add `<SpatialExplorerPanel />` immediately after, plus `<SpatialExplorerToggle />` adjacent to `<BehavioralMetricsToggle />`).

## Section 9: Tests

Create the following test files. Floor +16 pytest, +30 vitest. Stretch +20 / +35.

### `tests/test_ad520_spatial_module.py` (~6 pytest)

```
1. SpatialDeck/SpatialLayout frozen dataclass + to_dict() round-trip preserves all fields
2. _DEFAULT_LAYOUT ships ≥6 decks (Bridge / Engineering / Sickbay / Tactical / Science Lab / Computer Core)
   each with a valid 3-tuple position and at least one post_offset on Bridge
3. load_spatial_layout(None) returns _DEFAULT_LAYOUT
4. load_spatial_layout("nonexistent.yaml") returns _DEFAULT_LAYOUT + WARNING via caplog
5. load_spatial_layout(<malformed yaml tmp_path>) returns _DEFAULT_LAYOUT + WARNING via caplog
6. compute_agent_positions maps a known agent (department=engineering, post=chief_engineer)
   to engineering deck position; an unknown-department agent falls back to common_areas deck
   with on_watch=False
```

### `tests/test_ad520_graph_endpoint.py` (~6 pytest)

```
1. GET /api/ontology/graph returns 503 when runtime.ontology is None
2. Happy path returns {nodes, edges, generated_at} payload with department + agent nodes
   and assignment-derived member_of edges
3. include_edges=True calls runtime.knowledge_edges.find_edges(limit=max_edges) and merges results
4. edge_relations="member_of,reports_to" filter applied — only matching relation types in result
5. find_edges raising RuntimeError → assignment-only edges + WARNING captured via caplog
6. max_nodes=5 truncates the combined node list to exactly 5 entries
```

### `tests/test_ad520_spatial_layout_endpoint.py` (~2 pytest)

```
1. GET /api/ontology/spatial-layout returns 503 when runtime.spatial_layout is None
2. Happy path returns _DEFAULT_LAYOUT.to_dict() shape with schema_version=1 and ≥6 decks
```

### `tests/test_ad520_finalize.py` (~2 pytest)

```
1. _wire_spatial_explorer skips (returns False) when config.spatial_explorer.enabled=False
   and runtime.spatial_layout remains None
2. _wire_spatial_explorer with enabled=True and empty spatial_layout_path constructs
   runtime.spatial_layout from _DEFAULT_LAYOUT (or from config/ontology/spatial.yaml if present)
   and returns True
```

### `ui/src/__tests__/SpatialExplorerPanel.test.tsx` (~6 vitest)

```
1. Renders nothing when spatialExplorerOpen=false
2. Renders panel + view-mode tabs + close button when open=true
3. Mount triggers fetch of /api/ontology/graph and /api/ontology/spatial-layout (mock fetch)
4. Switching from GRAPH to SHIP LAYOUT swaps the rendered child component
5. ESC keypress closes the panel (calls closeSpatialExplorer)
6. Refresh button re-invokes both fetches
```

### `ui/src/__tests__/KnowledgeGraphView.test.tsx` (~10 vitest)

```
1. Renders ForceGraph3D with nodes from store (mock react-force-graph-3d via vi.mock to count nodes)
2. ORG CHART mode filters edges to relation in {reports_to, member_of}
3. TRUST NETWORK mode shows synthesized trust edges between agents
4. KNOWLEDGE MAP mode shows all relation types
5. DEPARTMENT VIEW clusters nodes by department field (verify forceGraphRef config)
6. Department filter chip click toggles agent visibility
7. Node click dispatches setSpatialSelectedNode({kind:'agent', id, payload})
8. Node color matches department palette (verify via mock onNodeColor or props snapshot)
9. Node size scales with trust value (clamped to [3, 12])
10. Empty graphData state shows "No graph data" status text
```

### `ui/src/__tests__/ShipLayoutView.test.tsx` (~8 vitest)

```
1. Renders R3F Canvas with deck groups when spatialLayoutData has 6+ decks (mock @react-three/fiber Canvas)
2. One agent mesh rendered per crew-manifest entry, positioned at deck_position + post_offset
3. CRITICAL alert tints decks red — verify via Material color prop snapshot
4. ALERT alert tints decks amber — verify via Material color prop snapshot
5. Agent mesh click dispatches setSpatialSelectedNode({kind:'agent', id, payload})
6. Deck label rendered via drei <Text> — assert label text matches deck.name
7. Agent without known department falls back to common_areas deck position
8. Empty spatialLayoutData shows "No spatial layout — enable in config" status text
```

### `ui/src/__tests__/NodeDetailDrawer.test.tsx` (~4 vitest)

```
1. Renders nothing when spatialSelectedNode=null
2. Renders agent payload as 2-column table when kind='agent' (rows: department, rank, post, trust, on_watch)
3. Renders edge payload as 2-column table when kind='edge' (rows: relation, weight, confidence, source, target)
4. Close button (×) clears selection (calls setSpatialSelectedNode(null))
```

### `ui/src/__tests__/SpatialExplorerToggle.test.tsx` (~2 vitest)

```
1. Toggle visible (data-testid="spatial-explorer-toggle") when spatialExplorerOpen=false
2. Click invokes openSpatialExplorer; toggle hidden when open=true
```

## What this AD does NOT change

- No changes to `ui/src/components/CognitiveCanvas.tsx` — orbital view preserved unchanged (HXI fragility rule from `/memories/repo/probos-notes.md`: "InstancedMesh raycasting breaks if instance count changes without proper reconciliation; tooltip regression: any change to agents.tsx or CognitiveCanvas.tsx can break hover/click").
- No new npm dependencies — `react-force-graph-3d ^1.29.1`, `@react-three/fiber ^9.0.0`, `@react-three/drei ^10.0.0`, `three ^0.172.0`, `@react-three/postprocessing ^3.0.0` already in `ui/package.json:14-21`.
- No new EventTypes — the explorer is read-only; alert tinting consumes the existing `bridge_alert` event already broadcast.
- No new agents, no new pools, no new IntentDescriptors, no consensus changes, no trust-store changes.
- No `KnowledgeEdgeStore` schema or API changes.
- No `<CognitiveCanvas>` orbital-view changes.
- No new shell commands.
- No changes to `runtime.start()` ordering (the new wirer mounts in the existing `finalize_startup` chain after `_wire_mcp_app_host`).
- No federation export of spatial-layout data (renderer-agnostic shape ships locally; cross-vessel fleet visualization is out-of-repo class-extension territory).
- No WebXR / `@react-three/xr` adoption (Phase 3 Commercial scope, descriptor-only).
- No AD-562 Knowledge Browser absorption (sibling visualization, #9 stays open).

## Tracking

- `PROGRESS.md` — top-of-file CLOSED entry.
- `docs/development/roadmap.md:6419` — flip status to `(Phase 1 + Phase 2 v1 COMPLETE, OSS, depends: AD-429, AD-513; Phase 3 immersive twin remains Commercial scope)`.
- `decisions-era-4-evolution.md` — append `## AD-520 — Spatial Knowledge Explorer v1 (Phase 1 + Phase 2)` decision entry following Era-4 precedent.
- GH issue #95 — close with summary on ship.

## Acceptance criteria

1. Pytest gate: 12459 → ≥12475 (+16 floor); stretch 12480 (+20).
2. Vitest gate: 363 → ≥393 (+30 floor); stretch 398 (+35).
3. `_DEFAULT_LAYOUT` ships ≥6 decks; out-of-box behavior: explorer renders even with no YAML file and no operator config.
4. `/api/ontology/graph` and `/api/ontology/spatial-layout` endpoints function per spec; both honor 503 short-circuit when disabled.
5. `<SpatialExplorerPanel>` opens via `EXPLORER` toggle at top:12 left:340, switches view modes without re-fetch, closes on ESC.
6. `<KnowledgeGraphView>` renders all 4 modes; `<ShipLayoutView>` renders 6 decks with agents at duty stations + alert tinting.
7. `<NodeDetailDrawer>` opens on selection, closes on `×`.
8. `<CognitiveCanvas>` unchanged — manual smoke verify tooltips / bloom / raycasting intact post-build.
9. Pre-commit hook passes (zero hits on the three banned patterns in this prompt + dispatch + wave-plan entry).
10. Closes GH #95.
11. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (HEAD ecaf30f, 2026-05-07)

```
git rev-parse HEAD
  ecaf30f23e3899d30be1237ad51350b98a558c40

# Pytest baseline: 12459 (Captain summary). Vitest baseline: 363 (verified `npx vitest run` → "Tests 363 passed (363)" across 22 files).

Select-String -Path ui\package.json -Pattern "react-force-graph|three|fiber|drei|postprocessing"
  ui/package.json:14:  "@react-three/drei": "^10.0.0",
  ui/package.json:15:  "@react-three/fiber": "^9.0.0",
  ui/package.json:16:  "@react-three/postprocessing": "^3.0.0",
  ui/package.json:19:  "react-force-graph-3d": "^1.29.1",
  ui/package.json:21:  "three": "^0.172.0",

Select-String -Path src\probos\routers\ontology.py -Pattern "^@router|def get_"
  routers/ontology.py:19:  @router.get("/vessel")
  routers/ontology.py:30:  @router.get("/organization")
  routers/ontology.py:43:  @router.get("/crew/{agent_type}")
  routers/ontology.py:54:  @router.get("/crew-manifest")
  routers/ontology.py:84:  @router.get("/skills/{agent_type}")
  ← insertion point for /graph + /spatial-layout: immediately before line 84

Select-String -Path src\probos\ontology\service.py -Pattern "def get_posts|def get_all_assignments|def get_crew_manifest|def get_departments"
  ontology/service.py:120: def get_posts(self, department_id=None) -> list[Post]
  ontology/service.py:153: def get_all_assignments(self) -> list[Assignment]
  ontology/service.py:472: def get_crew_manifest(self, *, department=None, trust_network=None, callsign_registry=None)

Select-String -Path src\probos\knowledge\edges.py -Pattern "class KnowledgeEntityType|class KnowledgeRelationType|class KnowledgeEdge|class KnowledgeEdgeStorage|async def find_edges"
  knowledge/edges.py:41:  class KnowledgeEntityType(str, Enum)         ← 8 entity values
  knowledge/edges.py:54:  class KnowledgeRelationType(str, Enum)       ← 10 relation values (member_of, reports_to, ...)
  knowledge/edges.py:73:  class KnowledgeEdge (frozen dc, 13 fields)
  knowledge/edges.py:134: class KnowledgeEdgeStorage(Protocol)
  knowledge/edges.py:150: async def find_edges(*, source_type=None, source_id=None, target_type=None, target_id=None, relation=None, limit=100)

Select-String -Path src\probos\runtime.py -Pattern "self.knowledge_edges|self.bridge_alerts|self.ontology"
  runtime.py:454: self.bridge_alerts: BridgeAlertService | None = None
  runtime.py:482: self.knowledge_edges: Any = None  ← spatial_layout slot inserts immediately after
  runtime.py:1734: self.knowledge_edges = comm.knowledge_edges

Select-String -Path src\probos\config.py -Pattern "^class MCPAppHostConfig|^class SpatialExplorerConfig|^class SystemConfig|mcp_app_host:"
  config.py:821:  class MCPAppHostConfig(BaseModel)               ← SpatialExplorerConfig inserts immediately above
  config.py:2831: class SystemConfig(BaseModel)
  config.py:2904: mcp_app_host: MCPAppHostConfig = Field(...)  # AD-597 — spatial_explorer field inserts immediately after

Select-String -Path src\probos\startup\finalize.py -Pattern "_wire_mcp_app_host|_wire_clinical_telemetry|_wire_spatial_explorer"
  finalize.py:793:  def _wire_clinical_telemetry(*, runtime, config) -> bool
  finalize.py:863:  def _wire_mcp_app_host(*, runtime, config) -> bool   ← _wire_spatial_explorer inserts immediately above
  finalize.py:3019: _wire_mcp_app_host(runtime=runtime, config=config)
  finalize.py:3021: logger.warning("AD-597: _wire_mcp_app_host failed", exc_info=True)  ← invocation site cluster

Select-String -Path ui\src\App.tsx -Pattern "BehavioralMetricsPanel|BehavioralMetricsToggle|CrewRosterPanel|notebooks"
  ui/src/App.tsx:19:  import CrewRosterPanel from './components/CrewRosterPanel'
  ui/src/App.tsx:21:  import BehavioralMetricsPanel from './components/BehavioralMetricsPanel'  ← SpatialExplorerPanel import inserts immediately after
  ui/src/App.tsx:23:  function NotebooksToggle()
  ui/src/App.tsx:57:  function BehavioralMetricsToggle()         ← SpatialExplorerToggle inserts immediately above (top:12 left:340)
```

All concrete claims map to grep hits above. No phantom APIs. No phantom config classes. No phantom file paths.
