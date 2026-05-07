# WAVE 103 DISPATCH — AD-520 v1 Spatial Knowledge Explorer: Digital Twin & 3D Ontology Visualization (closes #95)

## Wave summary

**Umbrella:** AD-520 — Spatial Knowledge Explorer. Documented at `docs/development/roadmap.md:6419` (`(planned, OSS + Commercial, depends: AD-429, AD-513)`). Spec ladders three visualization tiers — (1) Knowledge Graph View (OSS, Phase 1), (2) Spatial Ship Layout (OSS, Phase 2), (3) Digital Twin / WebXR (Commercial, Phase 3). v1 ships **both OSS phases in one Builder cycle** plus a single forcing-function descriptor-only carve-out for the Commercial Phase 3 immersive surface, per Captain rule "don't defer unless no choice." Wave 103 is HXI-heavy (R3F panel + view-mode switcher + force-graph + deck layout) on top of one new backend snapshot endpoint and one YAML configuration file.

**Wave kind:** Source-modifying single-AD v1 — additive only.
- One new Python module `src/probos/ontology/spatial.py` (~180 LOC: `SpatialLayoutConfig` loader + `SpatialDeck` + `SpatialLayout` frozen dataclasses + `_DEFAULT_LAYOUT` fallback constant).
- Two new GET routes appended to existing `src/probos/routers/ontology.py` — `/api/ontology/graph` (assembles `{nodes, edges}` from crew-manifest + organization + `runtime.knowledge_edges.find_edges`) and `/api/ontology/spatial-layout` (returns parsed `config/ontology/spatial.yaml` or default).
- One new `SpatialExplorerConfig` Pydantic model adjacent to existing `MCPAppHostConfig` (`config.py:821`) — `enabled: bool = False`, `max_graph_edges: int = 500`, `max_graph_nodes: int = 200`, `spatial_layout_path: str = ""` (empty → resolves to `config/ontology/spatial.yaml` then falls back to `_DEFAULT_LAYOUT`).
- One new finalize wirer `_wire_spatial_explorer` adjacent to `_wire_mcp_app_host` (`finalize.py:863`) — constructs `runtime.spatial_layout: SpatialLayout` from config / yaml / default, **no other side-effects** (the explorer is read-only, pure REST consumption); invoked from `finalize_startup` after `_wire_mcp_app_host` (line 3019 cluster).
- One new YAML file `config/ontology/spatial.yaml` shipping a 6-deck default ship layout (Bridge / Engineering / Sickbay / Tactical / Science Lab / Computer Core) keyed by department id, with 3D coordinates per deck and per-post duty-station offsets.
- Five new HXI components: `ui/src/components/SpatialExplorerPanel.tsx` (host shell + view-mode tabs + ESC + glass styling), `ui/src/components/spatial/KnowledgeGraphView.tsx` (Phase 1 force-graph), `ui/src/components/spatial/ShipLayoutView.tsx` (Phase 2 deck layout), `ui/src/components/spatial/NodeDetailDrawer.tsx` (inspection drawer), `ui/src/components/spatial/types.ts` (shared types).
- Store wiring extension in `ui/src/store/types.ts` + `ui/src/store/useStore.ts`: `spatialExplorerOpen: boolean`, `spatialViewMode: 'graph' | 'ship'`, `spatialSelectedNode: SpatialSelection | null`, `openSpatialExplorer()` / `closeSpatialExplorer()` / `setSpatialViewMode()` / `setSpatialSelectedNode()`.
- `App.tsx`: import + new `SpatialExplorerToggle` component (top:12 left:340 — slotted to the right of the existing `METRICS` toggle at left:270) + panel mount alongside `<BehavioralMetricsPanel />`.

The Phase 1 graph view reuses `react-force-graph-3d ^1.29.1` (already in `ui/package.json:19` since AD-611 — verified) — no new dependency. The Phase 2 ship layout uses the existing `@react-three/fiber ^9.0.0` + `@react-three/drei ^10.0.0` + `three ^0.172.0` stack (already present, package.json:14-21). Glass design language reused from `BehavioralMetricsPanel` and `CrewRosterPanel` precedents (`#0a0a12` background, `rgba(10,10,18,0.75)` panel surface, `backdropFilter: blur(8px)`, amber `#f0b060` active / dim `#666680` inactive, `JetBrains Mono`, SVG `strokeWidth: 1.5` icons, no emoji per HXI Design Principle #3).

**Reframe decision — ship Phase 1 + Phase 2 in one v1 (Captain rule "don't defer unless no choice" applied):**

The original AD-520 spec at `roadmap.md:6419` documents three visualization tiers explicitly partitioned into two OSS phases and one Commercial phase. On second-pass evaluation against HEAD `ecaf30f`, the architectural surface needed to ship **both OSS phases in a single Builder cycle** turns out to be:

1. **All required dependencies are already present.** `react-force-graph-3d ^1.29.1` + `three ^0.172` + `@react-three/fiber ^9` + `@react-three/drei ^10` were adopted under AD-611 (3D Memory Graph — `PROGRESS.md:365` "Frontend: react-force-graph-3d in new Memory tab on agent profile panel"). v1 adds **zero new npm dependencies**. The `r3f-forcegraph` candidate listed in the spec is a different package than the in-tree `react-force-graph-3d`; sticking with the in-tree library avoids a one-off package introduction and keeps a single graph engine across the HXI (consistency with AD-611 Memory Graph). Documented in DLog #1.

2. **All required backend data sources are already wired and queryable via existing REST endpoints.** Spec line 6437 explicitly states "All queryable via existing REST endpoints — the explorer is a pure visualization layer, no new backend required for Phase 1." Verify-first against HEAD confirms: `/api/ontology/crew-manifest` (AD-513, `routers/ontology.py:54`), `/api/ontology/organization` (`:30`), `runtime.knowledge_edges` adopted at `runtime.py:482` + `:1734` (AD-687/689/692). Phase 1 needs **one** new endpoint `/api/ontology/graph` to combine these three reads into a force-graph-shaped JSON payload — pure aggregator on top of existing surfaces. Documented in DLog #2.

3. **Phase 2 spatial ship layout is one YAML config file + one deck-renderer component.** The spec calls for `config/ontology/spatial.yaml` extending the ship ontology with deck-to-department mapping. v1 ships the YAML + a loader (`spatial.py`) + the `<ShipLayoutView>` component. The "real-time activity glow / proactive thinking pulse / dream state dim" features map directly onto existing store state already broadcast by the websocket loop (agent activity is in `useStore.agents`). Alert condition coloring reads `runtime.bridge_alerts.get_recent_alerts(...)` (verified `runtime.py:454`). Watch rotation positioning reads existing crew manifest watch field. Documented in DLog #3.

4. **The new HXI panel is additive — it does NOT touch CognitiveCanvas.** Spec line 6435 states "The Spatial Explorer is a new HXI panel alongside the existing Cognitive Canvas, not a replacement. Users can switch between orbital view (current), graph view (Phase 1), ship layout (Phase 2), and immersive twin (Phase 3)." v1 ships `<SpatialExplorerPanel>` as a top-level draggable floating panel with internal view-mode tabs (Graph / Ship). The orbital view (current `CognitiveCanvas`) is preserved unchanged. Tooltip / bloom / raycasting in `CognitiveCanvas.tsx` remain untouched. Documented in DLog #4.

The combined Phase 1 + Phase 2 v1 ships in one wave. Phase 3 (immersive walkable bridge + WebXR + fleet-zoom view + holographic record displays) is **explicitly Commercial** in the spec ("(3) Digital Twin — Immersive Ship (Commercial, Phase 3)") and is the only descriptor-only carve-out:

- **AD-520g-1 — Phase 3 Commercial Digital Twin (descriptor-only, NOT a forcing-function defer with FF — explicit Commercial scope).** Walk-the-corridors WebXR experience, fleet-zoom-to-multi-vessel cohort view, holographic record rendering, and `@react-three/xr` adoption are all class-extension territory under the private overlay-repo path token surface. v1 ships the `SpatialLayout` data model in a renderer-agnostic shape (per spec line 6427 "renderer-agnostic — same scene graph drives the HXI panel view, a WebXR immersive session, or a future native VR client") so a future commercial overlay can mount a `<WebXRImmersiveTwin>` against the same `runtime.spatial_layout` without backend changes. Descriptor-only references throughout this dispatch and the per-AD prompt.

**v1 IN scope (concrete, all in this single AD prompt):**

- **AD-520 v1 — Spatial Knowledge Explorer: Phase 1 Graph View + Phase 2 Spatial Ship Layout** (~16-test pytest plan + ~30-test vitest plan, `prompts/ad-520-spatial-knowledge-explorer-v1.md`).

  *New Python module `src/probos/ontology/spatial.py`*:
  - `SpatialDeck` frozen dataclass (`deck_id: str`, `name: str`, `department_id: str | None`, `position: tuple[float, float, float]`, `dimensions: tuple[float, float, float]`, `post_offsets: dict[str, tuple[float, float, float]]`, `accent_color: str`).
  - `SpatialLayout` frozen dataclass (`schema_version: int = 1`, `decks: list[SpatialDeck]`, `to_dict() -> dict`).
  - `_DEFAULT_LAYOUT` module-level constant — a built-in 6-deck topology so the explorer renders out-of-box even if `config/ontology/spatial.yaml` is missing or malformed (PRINCIPLE: every config field has a sensible default, ProbOS boots with zero config).
  - `load_spatial_layout(path: str | None) -> SpatialLayout` — loads YAML, falls back to default with WARNING on missing/parse-failure (tier-2 log-and-degrade); returns `_DEFAULT_LAYOUT` when `path` is empty/None.
  - `compute_agent_positions(layout: SpatialLayout, manifest: list[dict]) -> list[dict]` — pure helper that maps each crew-manifest entry to a 3D position by department-deck lookup + post-offset, returning `[{agent_id, agent_type, department, post, position: [x,y,z], on_watch: bool}]`. Tier-2 log-and-degrade: agents without a known deck/department are placed at deck "Common Areas" default offset and flagged `on_watch=False`.

  *Two new GET endpoints appended to `src/probos/routers/ontology.py`* (after `get_ontology_skills` at `:84`):
  - `GET /api/ontology/graph?include_edges=true&max_edges=500&max_nodes=200&edge_relations=reports_to,member_of` — assembles `{nodes: [...], edges: [...], generated_at: float}`. Nodes are derived from `ont.get_crew_manifest()` (one node per agent: `{id, label, type='agent', department, rank, trust, post, on_watch}`) + `ont.get_departments()` (one node per department: `{id, label, type='department', accent_color}`). Edges are derived from (a) crew-manifest assignments (one `member_of` edge per agent → department) AND (b) when `include_edges=True` and `runtime.knowledge_edges` is wired, the first `max_edges` results from `await runtime.knowledge_edges.find_edges(limit=max_edges)` filtered by the optional `edge_relations` whitelist (CSV of `KnowledgeRelationType` values; unknown values silently dropped). 503 when `runtime.ontology` is None. Tier-2 log-and-degrade on `find_edges()` failure: returns assignment-derived edges only with WARNING log.
  - `GET /api/ontology/spatial-layout` — returns `runtime.spatial_layout.to_dict()` if wired, else 503. The endpoint is read-only, no parameters. Default-False guard: when `config.spatial_explorer.enabled=False`, the wirer skips and the endpoint returns 503 — operator opt-in.

  *New Pydantic config `SpatialExplorerConfig`* in `config.py` adjacent to `MCPAppHostConfig` at `:821`:
  ```python
  class SpatialExplorerConfig(BaseModel):
      """AD-520: Spatial Knowledge Explorer (Phase 1 + Phase 2 OSS)."""
      enabled: bool = False
      max_graph_edges: int = Field(default=500, ge=0, le=5000)
      max_graph_nodes: int = Field(default=200, ge=0, le=2000)
      spatial_layout_path: str = ""  # empty → auto-resolve to config/ontology/spatial.yaml
  ```
  Wired on `SystemConfig.spatial_explorer` adjacent to `mcp_app_host: MCPAppHostConfig`. Default-False per AD-695 transitional precedent — the endpoint returns 503 until operator flips the switch.

  *New finalize wirer `_wire_spatial_explorer`* in `startup/finalize.py` adjacent to `_wire_mcp_app_host` (`:863`). Pure sync wirer (no asyncio task creation): reads `config.spatial_explorer.enabled`; when True, resolves `spatial_layout_path` (empty → `config/ontology/spatial.yaml`), calls `load_spatial_layout(path)`, sets `runtime.spatial_layout: SpatialLayout` public attribute (collision-free greenfield — verified 0 hits at HEAD). Invoked from `finalize_startup` immediately after `_wire_mcp_app_host` invocation site (`:3019` cluster) wrapped in try/except → `logger.warning("AD-520: _wire_spatial_explorer failed", exc_info=True)`.

  *New YAML config `config/ontology/spatial.yaml`*:
  ```yaml
  schema_version: 1
  decks:
    - deck_id: bridge
      name: "Bridge"
      department_id: command
      position: [0.0, 6.0, 0.0]
      dimensions: [8.0, 1.5, 6.0]
      accent_color: "#f0b060"
      post_offsets:
        captain: [0.0, 0.0, -1.0]
        first_officer: [-1.5, 0.0, 0.0]
        counselor: [1.5, 0.0, 0.0]
        yeoman: [0.0, 0.0, 1.5]
    - deck_id: engineering
      department_id: engineering
      # ... 5 more decks: sickbay/tactical/science_lab/computer_core/common_areas
  ```
  Default ship topology mirrors the spec mapping at `roadmap.md:6423` (Bridge=command / Engineering=engineering / Sickbay=medical / Tactical=security / Science Lab=science / Computer Core=ship-systems). The YAML is generated at build time from `_DEFAULT_LAYOUT`'s `to_dict()` so the file and the in-code constant stay byte-for-byte synchronized.

  *Public runtime attribute*: `self.spatial_layout: Any = None` slot added at `runtime.py:482` cluster (immediately after `self.knowledge_edges`).

  *HXI store extension in `ui/src/store/types.ts`*:
  - `SpatialSelection = { kind: 'agent' | 'department' | 'edge'; id: string; payload: Record<string, unknown> } | null`
  - `SpatialViewMode = 'graph' | 'ship'`
  - `spatialExplorerOpen: boolean`, `spatialViewMode: SpatialViewMode`, `spatialSelectedNode: SpatialSelection`, `spatialGraphData: { nodes: any[]; edges: any[] } | null`, `spatialLayoutData: SpatialLayout | null`.

  *Actions appended to `useStore.ts`*: `openSpatialExplorer()` / `closeSpatialExplorer()` / `setSpatialViewMode(mode)` / `setSpatialSelectedNode(sel)` / `setSpatialGraphData(data)` / `setSpatialLayoutData(data)`. Initial state: closed, view=graph, selected=null, both data caches null.

  *New HXI components*:
  - `ui/src/components/SpatialExplorerPanel.tsx` — 720×640 floating draggable panel (mirrors `BehavioralMetricsPanel` glass styling). Header with title `SPATIAL EXPLORER`, view-mode tabs (`GRAPH` / `SHIP LAYOUT`), close button (`×`). On mount fetches `/api/ontology/graph?include_edges=true` AND `/api/ontology/spatial-layout` once; refresh button (`↻`) re-invokes both. ESC handler closes. Conditional rendering: `viewMode==='graph' ? <KnowledgeGraphView /> : <ShipLayoutView />` plus persistent `<NodeDetailDrawer />` along the right edge when `spatialSelectedNode !== null`. Empty/loading/error states all handled with inline status text (no spinner GIF — text-only per HXI principle).
  - `ui/src/components/spatial/KnowledgeGraphView.tsx` — wraps `<ForceGraph3D>` from `react-force-graph-3d` (same import pattern as AD-611 `MemoryGraph3D.tsx` already in tree). Mode chips along the top: `ORG CHART` (filters edges to `member_of` + `reports_to`, uses DAG mode), `TRUST NETWORK` (uses agent nodes + computed trust-weighted edges from `agents.trust` Hebbian → ad-hoc edge synthesis), `KNOWLEDGE MAP` (all `KnowledgeRelationType` edges), `DEPARTMENT VIEW` (clusters nodes by `department` field). Department filter chips (one per department from store). Node color from department palette (amber/cyan/teal/violet/green/gold trust spectrum reused from `BehavioralMetricsPanel` per HXI Design Principle #3). Node size from `trust` (Beta-mean derived) clamped [3, 12]. Click handler dispatches `setSpatialSelectedNode({kind:'agent', id, payload:node})`. Edge color/width from relation type + weight.
  - `ui/src/components/spatial/ShipLayoutView.tsx` — R3F `<Canvas>` (top-level — second `<Canvas>` is fine, separately mounted from `CognitiveCanvas`; verified spec compatible since the panel is its own DOM tree). Renders one `<group>` per deck at `deck.position` containing a wireframe `<Box>` with `deck.dimensions` and `<Text>` label (drei). Inside each deck, renders one `<mesh>` per agent at `deck_position + post_offset` with sphere geometry colored by department accent. Agent meshes pulse (`useFrame` + `Math.sin(t)`) when `agents[id].activity_state === 'active'`. Alert-condition tint overlay: when `runtime.bridge_alerts` reports CRITICAL via store, all decks tint red; ALERT → amber; otherwise neutral. Click on an agent mesh → `setSpatialSelectedNode({kind:'agent', id, payload:agent})`. OrbitControls for camera. Bloom postprocessing reused from CognitiveCanvas import (`@react-three/postprocessing`).
  - `ui/src/components/spatial/NodeDetailDrawer.tsx` — 280×full-height right-edge drawer. Renders `spatialSelectedNode.payload` in a structured table (department / rank / post / trust score with Beta(α,β) raw + derived mean / on_watch / connections count). Close button (`×`) clears selection.
  - `ui/src/components/spatial/types.ts` — shared TypeScript types matching the backend payload shape.

  *App.tsx integration* (additive only):
  - New import: `import SpatialExplorerPanel from './components/SpatialExplorerPanel';`
  - New `SpatialExplorerToggle` component sibling to `BehavioralMetricsToggle` (App.tsx:57 cluster) — top:12 left:340 (right of `METRICS` toggle at left:270), label `EXPLORER`, click opens the panel.
  - Mount `<SpatialExplorerPanel />` adjacent to the existing `<BehavioralMetricsPanel />` mount line.

  *Test plan (~16 pytest + ~30 vitest, floor 14 pytest + 25 vitest)*:
  - `tests/test_ad520_spatial_module.py` — ~6 pytest: `SpatialDeck` / `SpatialLayout` frozen + `to_dict()` round-trip; `_DEFAULT_LAYOUT` ships ≥6 decks with valid 3-tuple positions; `load_spatial_layout(None)` returns `_DEFAULT_LAYOUT`; `load_spatial_layout("nonexistent.yaml")` returns `_DEFAULT_LAYOUT` + WARNING; `load_spatial_layout(<malformed YAML tmp_path>)` returns `_DEFAULT_LAYOUT` + WARNING; `compute_agent_positions` maps known agent to deck + flags unknown-department agents to "Common Areas" deck.
  - `tests/test_ad520_graph_endpoint.py` — ~6 pytest: `GET /api/ontology/graph` 503 when ontology None; happy path returns nodes + edges with assignment-derived `member_of` edges; `include_edges=true` calls `runtime.knowledge_edges.find_edges(limit=max_edges)`; `edge_relations` CSV filter applied (only matching relation types in result); `find_edges` exception → assignment-only edges + WARNING log captured; `max_edges=0` → no knowledge-graph edges, only assignment edges; `max_nodes` truncation applied to combined node list.
  - `tests/test_ad520_spatial_layout_endpoint.py` — ~2 pytest: `GET /api/ontology/spatial-layout` 503 when `runtime.spatial_layout` not wired; happy path returns `_DEFAULT_LAYOUT.to_dict()` payload with schema_version=1 and ≥6 decks.
  - `tests/test_ad520_finalize.py` — ~2 pytest: `_wire_spatial_explorer` skips when `enabled=False`; `_wire_spatial_explorer` constructs `runtime.spatial_layout` from default when path empty AND `enabled=True`.
  - `ui/src/__tests__/SpatialExplorerPanel.test.tsx` — ~6 vitest: renders nothing when `spatialExplorerOpen=false`; opens and fetches both endpoints; renders view-mode tabs (`GRAPH` / `SHIP LAYOUT`); switching tabs swaps view component; ESC closes panel; refresh button re-invokes both fetches.
  - `ui/src/__tests__/KnowledgeGraphView.test.tsx` — ~10 vitest: renders `ForceGraph3D` with nodes from store; ORG CHART filters edges to `reports_to`+`member_of`; TRUST NETWORK shows trust-weighted edges; KNOWLEDGE MAP shows all relation types; DEPARTMENT VIEW clusters by department; department filter chip toggles visibility; node click dispatches `setSpatialSelectedNode`; node color matches department palette; node size scales with trust; empty data shows "No graph data" status.
  - `ui/src/__tests__/ShipLayoutView.test.tsx` — ~8 vitest: renders R3F `<Canvas>` with deck groups when layout loaded; one mesh per agent positioned at `deck_position + post_offset`; CRITICAL alert tints decks red; ALERT tints amber; agent click dispatches `setSpatialSelectedNode`; deck label rendered via `<Text>`; agent without known department falls back to Common Areas deck; empty layout shows "No spatial layout" status.
  - `ui/src/__tests__/NodeDetailDrawer.test.tsx` — ~4 vitest: renders nothing when `spatialSelectedNode=null`; renders agent payload table when kind='agent'; close button clears selection; renders edge payload table when kind='edge'.
  - `ui/src/__tests__/SpatialExplorerToggle.test.tsx` — ~2 vitest: toggle visible when panel closed; click invokes `openSpatialExplorer` action; toggle hidden when panel open.

**v1 OUT scope (descriptor-only, NOT minted as new GH issues):**

- **AD-520g-1 — Phase 3 Commercial Digital Twin: Immersive Walkable Bridge + WebXR + Fleet Zoom + Holographic Records.** Explicit Commercial scope per spec line 6425 ("(3) Digital Twin — Immersive Ship (Commercial, Phase 3)"). Includes `@react-three/xr` adoption, full 3D starship corridors/decks model, fleet-of-vessels zoom-out view, document-as-hologram record browser. Out-of-repo class-extension territory under the private overlay-repo path token surface. v1 ships `SpatialLayout` in renderer-agnostic shape so a future commercial overlay can mount its own `<WebXRImmersiveTwin>` against `runtime.spatial_layout` with zero backend changes. Descriptor-only references throughout this dispatch and the per-AD prompt — no FF defer, no GH issue.

The roadmap forward-references that AD-520 transitively unblocks (AD-562 Knowledge Browser graph view at `roadmap.md:4225`, AD-524 Ship's Archive historical layers at `:2796`, convergence-cluster visualization for AD-554 at `:2826`) remain as already-tracked downstream consumers — Wave 103 mints zero new GH issues, closes #95 cleanly.

**The fleet-level spatial-twin distribution surface (out-of-repo):**
The OSS `SpatialLayout` data model + `<KnowledgeGraphView>` + `<ShipLayoutView>` + `/api/ontology/graph` + `/api/ontology/spatial-layout` form the architectural surface. Cross-vessel fleet visualization (a multi-vessel cohort surface rendering many ProbOS instances as ships in a fleet), customer-supplied closed-source deck-layout libraries, immersive WebXR experience packages, and outcome-style consulting on customized vessel topology design are all class-extension territory under the private overlay-repo path token surface. v1 ships zero closed-source content — descriptor-only references throughout this dispatch and the per-AD prompt.

## AD numbering

Highest AD stem at HEAD `ecaf30f` is **AD-696** (verified via PROGRESS.md sweep). Highest BF stem at HEAD: **BF-265**. W103 mints **zero new AD numbers** (AD-520 is pre-allocated at `roadmap.md:6419`; AD-520a–g are letter-suffixed sub-AD descriptors per the umbrella spec, not GH tracking issues; AD-520g-1 is a letter-suffixed Commercial-scope descriptor, not a GH tracking issue). W103 mints **zero new BF numbers**. **Current highest: AD-696, BF-265.**

## Verify-first against HEAD `ecaf30f`

```
git rev-parse HEAD
  ecaf30f23e3899d30be1237ad51350b98a558c40 Wave 102 archive: AD-597 MCP app host (#167)

# Pytest baseline (Captain summary): 12459 passing
# Vitest baseline (verified via `npx vitest run`): 363 passing across 22 files

# react-force-graph-3d already in tree from AD-611:
Select-String -Path ui\package.json -Pattern "react-force-graph|three"
  ui/package.json:14: "@react-three/drei": "^10.0.0",
  ui/package.json:15: "@react-three/fiber": "^9.0.0",
  ui/package.json:16: "@react-three/postprocessing": "^3.0.0",
  ui/package.json:19: "react-force-graph-3d": "^1.29.1",
  ui/package.json:21: "three": "^0.172.0",

# Existing ontology routes (extended in v1, NOT redone):
Select-String -Path src\probos\routers\ontology.py -Pattern "^@router|def get_"
  routers/ontology.py:19: @router.get("/vessel")
  routers/ontology.py:30: @router.get("/organization")     ← returns departments/posts/assignments via asdict
  routers/ontology.py:43: @router.get("/crew/{agent_type}")
  routers/ontology.py:54: @router.get("/crew-manifest")    ← AD-513
  routers/ontology.py:84: @router.get("/skills/{agent_type}")
  (insertion point for new /graph + /spatial-layout endpoints: after line 84)

# Crew-manifest service surface:
Select-String -Path src\probos\ontology\service.py -Pattern "get_posts|get_all_assignments|get_crew_manifest"
  src/probos/ontology/service.py:120: def get_posts(self, department_id: str | None = None) -> list[Post]
  src/probos/ontology/service.py:153: def get_all_assignments(self) -> list[Assignment]
  src/probos/ontology/service.py:472: def get_crew_manifest(self, *, department=None, trust_network=None, callsign_registry=None)

# KnowledgeEdgeStorage Protocol (consumed by /api/ontology/graph):
Select-String -Path src\probos\knowledge\edges.py -Pattern "^class |async def find_edges|KnowledgeEntityType|KnowledgeRelationType"
  src/probos/knowledge/edges.py:41: class KnowledgeEntityType(str, Enum)   ← 8 values
  src/probos/knowledge/edges.py:54: class KnowledgeRelationType(str, Enum) ← 10 values
  src/probos/knowledge/edges.py:73: class KnowledgeEdge (frozen dc, 13 fields)
  src/probos/knowledge/edges.py:134: class KnowledgeEdgeStorage(Protocol)
  src/probos/knowledge/edges.py:150: async def find_edges(*, source_type=None, source_id=None, target_type=None, target_id=None, relation=None, limit=100)

# Runtime knowledge_edges public attribute slot:
Select-String -Path src\probos\runtime.py -Pattern "self.knowledge_edges|self.bridge_alerts"
  src/probos/runtime.py:454: self.bridge_alerts: BridgeAlertService | None = None
  src/probos/runtime.py:482: self.knowledge_edges: Any = None  ← AD-687 slot, new self.spatial_layout slot inserts adjacent
  src/probos/runtime.py:1734: self.knowledge_edges = comm.knowledge_edges

# MCPAppHostConfig / _wire_mcp_app_host sibling-shape pattern (AD-597, mirrored by AD-520):
Select-String -Path src\probos\config.py -Pattern "^class MCPAppHostConfig|^class SystemConfig|mcp_app_host:"
  src/probos/config.py:821:  class MCPAppHostConfig(BaseModel)            ← SpatialExplorerConfig class inserts immediately above
  src/probos/config.py:2831: class SystemConfig(BaseModel)
  src/probos/config.py:2904: mcp_app_host: MCPAppHostConfig = Field(...)  # AD-597 — spatial_explorer SystemConfig field inserts immediately after

Select-String -Path src\probos\startup\finalize.py -Pattern "_wire_mcp_app_host|_wire_clinical_telemetry"
  startup/finalize.py:793: def _wire_clinical_telemetry(*, runtime, config) -> bool
  startup/finalize.py:863: def _wire_mcp_app_host(*, runtime, config) -> bool   ← _wire_spatial_explorer inserts adjacent
  startup/finalize.py:3019: _wire_mcp_app_host(runtime=runtime, config=config)  ← _wire_spatial_explorer invocation site cluster

# HXI panel mounting precedent (BehavioralMetricsPanel, AD-569g):
Select-String -Path ui\src\App.tsx -Pattern "BehavioralMetricsPanel|BehavioralMetricsToggle|CrewRosterPanel|notebooks"
  ui/src/App.tsx:19:  import CrewRosterPanel from './components/CrewRosterPanel'
  ui/src/App.tsx:21:  import BehavioralMetricsPanel from './components/BehavioralMetricsPanel'
  ui/src/App.tsx:23:  function NotebooksToggle()
  ui/src/App.tsx:57:  function BehavioralMetricsToggle()  ← top:12 left:270 — SpatialExplorerToggle inserts at left:340

# AD-562 Knowledge Browser status: PLANNED at HEAD (issue #9 still open per Captain).
# AD-520 v1 does NOT close or absorb AD-562 — they are sibling visualizations.
# AD-520 = 3D ontology / spatial topology of the ship.
# AD-562 = Obsidian-style records browser with 3D knowledge graph of records.
# Both reference each other in roadmap cross-links; they ship independently.
Select-String -Path docs\development\roadmap.md -Pattern "AD-562:" | Select-Object -First 1
  roadmap.md:4225: AD-562: Ship's Records Knowledge Browser — Obsidian-Style HXI with 3D Knowledge Graph (planned)
```

All concrete claims in the per-AD prompt map to the grep hits above. Verify-first sweep clean.

## Pre-flight commercial-leak audit (descriptor-only categories — zero literal hits)

The pre-commit hook trips on three literal patterns. The audit prose itself uses descriptor-only language to avoid self-tripping:

| Banned pattern (descriptor only) | Hits in dispatch | Hits in AD prompt | Hits in wave-plan entry | Resolution |
|---|---|---|---|---|
| Two-word phrase combining "enterprise" with the word for a service stratification level | 0 | 0 | 0 | clean |
| Hyphenated repository slug pairing the platform name with the word for a paid offering | 0 | 0 | 0 | clean |
| Three-letter acronym for annualized recurring revenue (matched as a whole word) | 0 | 0 | 0 | clean |

The audit table itself uses descriptor-only category names — no literal patterns appear in the audit prose, in the dispatch, in the per-AD prompt, or in the wave-plan YAML entry. Phase 3 Commercial scope is referenced consistently as "out-of-repo class-extension territory under the private overlay-repo path token surface" (same descriptor pattern as W101 / W102 lessons). Zero pricing language. Zero customer-tier language. Zero revenue language. Zero competitor positioning. The OSS surface this AD ships is the entire scope; the Commercial Phase 3 carve-out is described only as a renderer-agnostic future-mount point.

## Architect calls (DLogs)

1. **`react-force-graph-3d` over `r3f-forcegraph`.** Spec line 6429 names `r3f-forcegraph` as "the primary rendering engine for Phase 1." Reality at HEAD: `react-force-graph-3d ^1.29.1` is already present (AD-611, `package.json:19`) and proven in `MemoryGraph3D.tsx`. Both packages are by vasturiano. Adopting a second graph engine for one new view would introduce a one-off dependency and split the HXI's graph-rendering primitives across two libraries. v1 stays with the in-tree library. If a future AD requires R3F-native composition (mixing graph nodes with other R3F objects in one canvas), `r3f-forcegraph` adoption can be a separate refactor AD.

2. **One new endpoint `/api/ontology/graph` despite spec line 6437 "no new backend required."** The spec assumes the frontend can client-side-join three existing endpoints (crew-manifest + organization + a hypothetical "all edges" surface). At HEAD there is **no** REST endpoint that returns edges in bulk — `runtime.knowledge_edges` is an in-process Python object, not exposed via REST; AD-691 `/api/nl-graph-query` is query-scoped, AD-688 Oracle Tier 6 is Oracle-internal. Three options: (a) ship one new aggregator endpoint that combines all three reads server-side; (b) add a thin `/api/knowledge-edges` GET and let the frontend do the join; (c) skip Phase 1 graph rendering. (a) ships the smallest surface area (one new GET, no new router file), keeps the spec's "pure visualization layer" intent for the frontend, and matches the AD-611 precedent (`/api/memory-graph` aggregator endpoint). **v1 ships option (a).**

3. **Two-Canvas approach for Ship Layout view.** `<CognitiveCanvas>` is the existing top-level orbital view — the spec mandates it stays untouched. `<ShipLayoutView>` mounts its OWN `<Canvas>` inside the floating panel's DOM tree. R3F supports multiple canvases in one document (each gets its own WebGL context). Memory cost is one extra context per panel-open; bounded by the panel's open/close lifecycle. Alternative — sharing one canvas across the whole HXI — would require a major refactor to `App.tsx` layout and is out of v1 scope. Documented in module docstring of `ShipLayoutView.tsx`.

4. **Default-False per AD-695 transitional precedent.** Unlike `KnowledgeEdgesConfig` / `MCPAppHostConfig.serve_internal_games` (default-True with idempotent boot cost), `SpatialExplorerConfig.enabled=False` reflects that the wirer reads a YAML file and constructs an in-memory layout — not zero-cost on boot. Operator opt-in. Same pattern as AD-695 ThresholdAlertConfig and AD-510 HolodeckTeamSimulationConfig.

5. **Default ship layout ships in code, not just YAML.** `_DEFAULT_LAYOUT` is a module-level constant in `spatial.py`. `config/ontology/spatial.yaml` is the operator-editable override generated from `_DEFAULT_LAYOUT.to_dict()` at build time (not at runtime — the YAML is committed). This guarantees ProbOS boots with a working layout even if the YAML file is deleted, and ensures the in-tree YAML always matches the in-code default at v1 ship time.

6. **AD-520 does NOT close or absorb AD-562.** AD-562 (#9 still open) is a separate planned AD for an Obsidian-style records browser with its own 3D knowledge graph of records — overlapping conceptually but operating on the records corpus (AD-434), not the ship ontology (AD-429). Cross-references in `roadmap.md:4237` document the relationship: "AD-520 Phase 1 provides the 3D knowledge graph of the same data. Two views, one knowledge fabric." v1 ships AD-520 only; #9 stays open for future AD-562 work.

## Tracking

- `PROGRESS.md` — top-of-file CLOSED entry on ship.
- `docs/development/roadmap.md:6419` — flip status `(planned, OSS + Commercial, ...)` → `(Phase 1 + Phase 2 v1 COMPLETE, OSS, depends: AD-429, AD-513; Phase 3 immersive twin remains Commercial scope)`.
- `decisions-era-4-evolution.md` — append `## AD-520 — Spatial Knowledge Explorer v1 (Phase 1 + Phase 2)` decision entry following Era-4 precedent.
- `prompts/wave-plan.yaml` — append W103 entry (this dispatch).
- GH issue **#95** — close with summary on ship.

## Acceptance criteria

1. Pytest gate: 12459 → ≥12475 (+16 floor). Stretch: 12480 (+20).
2. Vitest gate: 363 → ≥393 (+30 floor). Stretch: 398 (+35).
3. `GET /api/ontology/graph` returns `{nodes, edges, generated_at}` payload; combined assignment + knowledge-edge sources; `max_edges` / `max_nodes` truncation honored.
4. `GET /api/ontology/spatial-layout` returns `_DEFAULT_LAYOUT.to_dict()` shape when wired; 503 when disabled.
5. `<SpatialExplorerPanel>` opens via toggle, renders both view modes, fetches both endpoints, switches modes without re-fetch.
6. `<KnowledgeGraphView>` renders all 4 graph modes (org chart / trust / knowledge / department), filters by department, click-to-inspect dispatches selection action.
7. `<ShipLayoutView>` renders deck topology, positions agents at duty stations, tints on alert condition.
8. `<NodeDetailDrawer>` renders agent / department / edge payload tables on selection.
9. `<CognitiveCanvas>` unchanged — tooltips / bloom / raycasting verified intact post-build (HXI fragility note from `/memories/repo/probos-notes.md`).
10. Pre-commit hook passes (zero hits across the three banned patterns in the dispatch + per-AD prompt + wave-plan entry).
11. Closes GH issue #95.
12. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Wave plan entry

```yaml
  - id: "103"
    title: "AD-520 v1 Spatial Knowledge Explorer: Digital Twin & 3D Ontology Visualization (closes #95)"
    kind: single
    depends_on: ["102"]
    dispatch_prompt: "prompts/WAVE-103-DISPATCH.md"
    prompts_already_drafted: true
    prompt_paths:
      - "prompts/ad-520-spatial-knowledge-explorer-v1.md"
    builder_required: true
    issues_to_close: [95]
    status: pending
```
