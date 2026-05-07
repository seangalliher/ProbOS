# WAVE 104 DISPATCH — AD-562 v1 Ship's Records Knowledge Browser: Obsidian-Style HXI with 3D Knowledge Graph (closes #9)

## Wave summary

**Umbrella:** AD-562 — Ship's Records Knowledge Browser. Documented at `docs/development/roadmap.md:4223` (`(planned, OSS+commercial, depends: AD-434, AD-551, AD-555)`) and `decisions-era-4-evolution.md:2330-2356` (status: Planned). Spec partitions five sub-deliverables — (1) Knowledge Browser core (OSS), (2) Backlinks & Cross-References (OSS), (3) 3D Force-Directed Knowledge Graph (OSS), (4) Convergence & Quality Overlays (OSS, depends AD-551 + AD-555), and (5) Native App Packaging (commercial). v1 ships **all four OSS sub-deliverables in one Builder cycle** plus a single descriptor-only commercial carve-out for the native packaging surface, per Captain rule "don't defer unless no choice." Wave 104 is HXI-heavy (browser panel + four sub-views: list / reader / 3D graph / timeline + backlinks rail) on top of one new pure-Python helper module, four new REST endpoints appended to the existing records router, one Pydantic config model, and one finalize wirer.

AD-562 also officially supersedes AD-523c (Ship's Records Dashboard) — confirmed at `decisions-era-4-evolution.md:2337` ("AD-523c (Ship's Records Dashboard) — planned feature for records browsing. AD-562 supersedes and absorbs this") and `:2350` ("AD-523c (Ship's Records Dashboard) was a simpler browsing view. AD-562 is the full-featured replacement with graph visualization, backlinks, and quality overlays"). Wave 77 already closed AD-523c as superseded (`prompts/archive/WAVE-77-DISPATCH.md:19`). No tracker work for AD-523c remains in W104.

**Wave kind:** Source-modifying single-AD v1 — additive only.
- One new Python module `src/probos/knowledge/backlinks.py` (~160 LOC: `Reference` + `BacklinkRecord` + `BacklinkIndex` frozen dataclasses; `extract_references(content, frontmatter, *, valid_callsigns) -> list[Reference]`; `build_backlink_index(entries: list[dict], *, valid_callsigns) -> BacklinkIndex`; `suggest_cross_references(entries, *, jaccard_threshold, max_per_entry) -> dict[str, list[dict]]`).
- Four new GET routes appended to existing `src/probos/routers/records.py` (after `get_record_history` at `:131`):
  - `GET /api/records/browse` — unified entry listing across all sub-directories with filters (`author`, `department`, `classification`, `directory`, `tags`, `since`, `until`); returns `{entries, count, filters_applied}`.
  - `GET /api/records/backlinks/{path:path}` — `{path, references: [...], referenced_by: [...], suggested: [...]}`. 404 on missing entry. Tier-2 log-and-degrade on extraction failure (returns empty arrays + WARNING).
  - `GET /api/records/graph?max_nodes=&max_edges=&include_suggested=&include_quality=` — assembles `{nodes, edges, generated_at}` shaped for `react-force-graph-3d`. Nodes = entries (`{id: path, label, type, department, classification, author, revision_count, is_convergence_hub, quality_overlay}`); edges = explicit backlinks (solid) + Jaccard suggestions (when `include_suggested=True`, dashed) + convergence-cluster membership (one edge per contributing agent → convergence-report path). Honors `max_nodes`/`max_edges` caps from `KnowledgeBrowserConfig`. 503 when `runtime.knowledge_browser` is None (default-False precedent).
  - `GET /api/records/timeline?bucket=day&since=&until=` — `{buckets: [{date, count, by_department}], total, bucket: "day"}`. Pure aggregator over `list_entries()` frontmatter `created` field. Bucket "day" only in v1 (week/month is forcing-function defer if surfaced).
- One new `KnowledgeBrowserConfig` Pydantic model in `config.py` adjacent to `SpatialExplorerConfig` (`config.py:821`) — `enabled: bool = False`, `max_graph_edges: int = 1000`, `max_graph_nodes: int = 500`, `jaccard_threshold: float = 0.3`, `max_suggestions_per_entry: int = 5`, `index_refresh_seconds: int = 300`. Wired on `SystemConfig.knowledge_browser` adjacent to `spatial_explorer` field at `config.py:2918`.
- One new finalize wirer `_wire_knowledge_browser` adjacent to `_wire_spatial_explorer` (`startup/finalize.py:863`) — constructs `runtime.knowledge_browser: KnowledgeBrowserService | None` (lazy backlink index + cached entries + suggestion cache, refreshes on TTL); invoked from `finalize_startup` immediately after `_wire_spatial_explorer` (`:3046`).
- One new service class `KnowledgeBrowserService` (~140 LOC, lives at the bottom of `knowledge/backlinks.py` to keep the new module self-contained) — `async def get_index(force_refresh=False) -> BacklinkIndex`, `async def get_graph(...)`, `async def get_timeline(...)`. Wraps the pure helpers + caches the result with TTL. Tier-2 log-and-degrade everywhere (returns empty `BacklinkIndex` on any failure).
- Eight new HXI components (~1000 LOC total): `ui/src/components/KnowledgeBrowserPanel.tsx` (800×640 host shell + ESC + glass styling + view-mode tabs + filter rail + backlinks rail), `ui/src/components/knowledge/EntryListView.tsx`, `ui/src/components/knowledge/EntryReader.tsx`, `ui/src/components/knowledge/RecordsGraphView.tsx`, `ui/src/components/knowledge/TimelineView.tsx`, `ui/src/components/knowledge/BacklinksRail.tsx`, `ui/src/components/knowledge/FilterRail.tsx`, `ui/src/components/knowledge/types.ts` (shared types).
- Store wiring extension in `ui/src/store/types.ts` + `ui/src/store/useStore.ts`: `knowledgeBrowserOpen: boolean`, `knowledgeBrowserView: 'list' | 'reader' | 'graph' | 'timeline'`, `knowledgeBrowserSelectedPath: string | null`, `knowledgeBrowserFilters: KnowledgeBrowserFilters`, `knowledgeBrowserEntries`, `knowledgeBrowserSelectedDoc`, `knowledgeBrowserBacklinks`, `knowledgeBrowserGraphData`, `knowledgeBrowserTimeline`, plus `openKnowledgeBrowser()`, `closeKnowledgeBrowser()`, `setKnowledgeBrowserView()`, `setKnowledgeBrowserFilters()`, `selectKnowledgeBrowserEntry(path)`, `refreshKnowledgeBrowser()`.
- `App.tsx`: import + new `KnowledgeBrowserToggle` component (`top:12 left:410` — slotted to the right of `SpatialExplorerToggle` at `left:340`) + panel mount alongside `<SpatialExplorerPanel />`.

The Phase 3 graph view reuses `react-force-graph-3d ^1.29.1` (in `ui/package.json:19` since AD-611, also reused by AD-520 — verified) — **zero new npm dependencies**. Glass design language reused from `NotebooksPanel`, `BehavioralMetricsPanel`, and `SpatialExplorerPanel` precedents (`#0a0a12` background, `rgba(10,10,18,0.85)` panel surface, `backdropFilter: blur(8px)`, amber `#f0b060` active / dim `#666680` inactive, `JetBrains Mono`, SVG `strokeWidth: 1.5` icons, no emoji per HXI Design Principle #3). Department/classification color tokens reused verbatim from `NotebooksPanel.tsx:15-29` (one source of truth across record surfaces).

**Reframe decision — ship Phases 1+2+3+4 in one v1 (Captain rule "don't defer unless no choice" applied):**

The original AD-562 spec at `roadmap.md:4225-4253` documents five sub-deliverables explicitly partitioned into four OSS phases and one commercial phase. On verify-first evaluation against HEAD `d8b7c63`, the architectural surface needed to ship **all four OSS phases in a single Builder cycle** is concretely tractable:

1. **All required backend dependencies are at HEAD.** RecordsStore (`knowledge/records_store.py:700` `read_entry`, `:731` `list_entries`, `:819` `search`, `:942` `_parse_document`) ships under AD-434 — no API extensions to existing methods needed. Phase 4 quality overlays consume `_notebook_quality_engine` (verified `routers/system.py:353-389` with `/api/notebook-quality{,/history,/agent/{callsign}}` all live). Phase 4 convergence-hub detection reads from `convergence-reports/` subdirectory (one Python `if path.startswith("convergence-reports/")` check on the entry list — no new code path needed; AD-551 already writes those reports). Phase 2 cross-reference suggestions can directly reuse the existing `KnowledgeLinter._suggest_cross_references()` helper at `knowledge/knowledge_linter.py:126` (Jaccard-based, exact pattern AD-562 spec line 4253 calls for). Documented in DLog #1.

2. **All required frontend dependencies are present.** `react-force-graph-3d ^1.29.1` (in-tree since AD-611, reused by AD-520 Wave 103) drives the Phase 3 records graph with zero new npm packages. Markdown rendering can ship as a minimal in-component renderer (~30 LOC: split on lines, handle `# heading`, `**bold**`, `[wikilinks]`, fenced code; spec does NOT require a full CommonMark engine for v1 and adding `marked`/`react-markdown` is gratuitous package introduction). Documented in DLog #2.

3. **Phase 2 backlink scanning is one pure helper module.** `extract_references()` is regex-based (`\[\[([^\]]+)\]\]` for explicit wikilinks, `@(\w+)` filtered against `valid_callsigns` for callsign mentions, frontmatter `tags` and `topic_slug` for topic-based linking). `build_backlink_index()` is one O(n) pass over the result. No LLM, no embeddings, no new dependencies. Documented in DLog #3.

4. **The new HXI panel is additive — it does NOT touch CognitiveCanvas, NotebooksPanel, or SpatialExplorerPanel.** Spec line 4225-4226 frames the Knowledge Browser as a unified surface above the existing fragmented record-surfaces. v1 ships `<KnowledgeBrowserPanel>` as a top-level draggable floating panel (800×640) with internal view-mode tabs (List / Reader / Graph / Timeline) and a left filter rail + right backlinks rail. NotebooksPanel (AD-523b) is preserved unchanged — it remains the focused notebook-only surface; Knowledge Browser is the unified-records surface. The two coexist (operator can have both open). CognitiveCanvas (HXI fragility rule per `.github/copilot-instructions.md`) untouched. Documented in DLog #4.

5. **Records-graph and ontology-graph are different graphs — no conflict with AD-520.** AD-520's `/api/ontology/graph` (`routers/ontology.py:84`) ships entries-as-departments and crew-as-agents — an organizational topology. AD-562's `/api/records/graph` ships entries-as-documents and references-as-edges — an epistemic topology. Different node sets, different edge semantics, complementary surfaces. No shared state, no shared cache. Documented in DLog #5.

The combined Phase 1 + Phase 2 + Phase 3 + Phase 4 v1 ships in one wave. Phase 5 (native desktop app packaging via Tauri/Electron) is **explicitly commercial-tagged** in the spec ("(5) Native App Packaging (commercial)" at `roadmap.md:4253`) and is the only descriptor-only carve-out:

- **AD-562-e — Phase 5 commercial native packaging (descriptor-only, NOT a forcing-function defer with FF — explicit commercial scope).** Tauri/Electron desktop wrapper, offline-first local search indexing, OS-level integration (file associations, system-tray, notification surfaces), and code-signing/notarization workflows are all class-extension territory under the private overlay-repo path token surface. v1 ships the OSS web HXI knowledge browser as the visualization layer; a future commercial overlay can wrap the same SPA into a desktop binary without touching the OSS surface (the React app is already self-contained at `ui/dist/`). Descriptor-only references throughout this dispatch and the per-AD prompt — no GH issue minted, no FF defer recorded, no commercial-roadmap entry created in OSS files.

**v1 IN scope (concrete, all in this single AD prompt):**

- **AD-562 v1 — Ship's Records Knowledge Browser: Obsidian-Style HXI with 3D Knowledge Graph** (~28-test pytest plan + ~32-test vitest plan, `prompts/ad-562-records-knowledge-browser-v1.md`).

  *New Python module `src/probos/knowledge/backlinks.py`*:
  - `Reference` frozen dataclass (`kind: str` ∈ {"wikilink","callsign","topic_slug","tag"}, `target: str`, `raw_match: str`).
  - `BacklinkRecord` frozen dataclass (`path: str`, `references: tuple[Reference, ...]`, `referenced_by: tuple[str, ...]`).
  - `BacklinkIndex` frozen dataclass (`records: dict[str, BacklinkRecord]`, `path_by_callsign: dict[str, str]`, `path_by_topic_slug: dict[str, str]`, `built_at: float`, `entry_count: int`).
  - `extract_references(content: str, frontmatter: dict, *, valid_callsigns: set[str], valid_topic_slugs: set[str]) -> tuple[Reference, ...]` — pure helper, no I/O. `_WIKILINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")`, `_CALLSIGN_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z][A-Za-z0-9_-]{1,31})")`. Frontmatter `tags` and `topic_slug` contribute `kind="tag"`/`kind="topic_slug"` references. Tier-2 log-and-degrade on regex failure (returns `()` + WARNING).
  - `build_backlink_index(entries: list[dict], *, valid_callsigns: set[str]) -> BacklinkIndex` — single pass: build path-by-callsign and path-by-topic-slug lookup tables, extract references per entry, then second pass to fill `referenced_by` via reverse mapping. Empty-input safe (`entries=[]` → `BacklinkIndex(records={}, path_by_callsign={}, path_by_topic_slug={}, built_at=time.time(), entry_count=0)`).
  - `suggest_cross_references(entries: list[dict], existing_index: BacklinkIndex, *, jaccard_threshold: float = 0.3, max_per_entry: int = 5) -> dict[str, list[dict]]` — for each entry compute Jaccard over `(frontmatter.get("tags", []) + topic-slug + author)` token sets vs every other entry; return top-N pairs above threshold that are NOT already in `references` or `referenced_by`. Dedup by sorted `(a, b)` pair.

  *New service class `KnowledgeBrowserService`* (bottom of `backlinks.py`, ~140 LOC):
  - `__init__(records_store, notebook_quality_engine, *, max_graph_nodes=500, max_graph_edges=1000, jaccard_threshold=0.3, max_suggestions_per_entry=5, index_refresh_seconds=300)`.
  - `async def get_index(*, force_refresh=False) -> BacklinkIndex` — caches; refreshes when `time.time() - built_at > ttl`.
  - `async def get_graph(*, max_nodes, max_edges, include_suggested, include_quality, department_filter=None, classification_filter=None) -> dict` — assembles force-graph payload. Nodes from index entries (capped at `max_nodes`); edges from explicit backlinks (solid `kind="backlink"`) + Jaccard suggestions when `include_suggested` (dashed `kind="suggested"`) + convergence-membership when entry path starts with `"convergence-reports/"` (one edge per contributing-agent callsign in entry frontmatter `contributing_agents` list, `kind="convergence"`). Quality overlay: if `include_quality` AND `notebook_quality_engine` present, attach `quality_overlay: {novel_content_rate, repetition_alerts, stale_rate}` to author-callsign nodes by reading `await engine.get_agent_snapshot(callsign)` (tier-2 log-and-degrade per agent).
  - `async def get_timeline(*, bucket="day", since="", until="") -> dict` — buckets entries by `frontmatter.created` ISO date (day-only in v1). Returns `{buckets: [{date, count, by_department: {dept: count}}], total, bucket}`. Empty-input safe.

  *Four new GET endpoints appended to `src/probos/routers/records.py`* (after `get_record_history` at `:131`):
  - `GET /api/records/browse?author=&department=&classification=&directory=&tags=&since=&until=` — unified entry list. CSV-decodes `tags` (intersection match). `since`/`until` are ISO date strings; entries with no `created` frontmatter are dropped from filtered ranges. Returns `{documents, count, filters_applied}`. 503 when `runtime._records_store` is None. Tier-2 log-and-degrade on `list_entries()` failure (logs WARNING, returns empty list).
  - `GET /api/records/backlinks/{path:path}?include_suggested=true` — returns `{path, references, referenced_by, suggested}`. 404 if entry not in index. 503 when `runtime.knowledge_browser` None. Tier-2 log-and-degrade on extraction failure.
  - `GET /api/records/graph?max_nodes=&max_edges=&include_suggested=&include_quality=&department=&classification=` — wraps `KnowledgeBrowserService.get_graph()`. Caps `max_nodes` to [0, 2000] and `max_edges` to [0, 5000] before delegation. 503 when `runtime.knowledge_browser` None.
  - `GET /api/records/timeline?bucket=day&since=&until=` — wraps `KnowledgeBrowserService.get_timeline()`. Bucket "day" only in v1 (other values 400). 503 when `runtime.knowledge_browser` None.

  *New Pydantic config `KnowledgeBrowserConfig`* in `config.py` adjacent to `SpatialExplorerConfig` at `:821`:
  ```python
  class KnowledgeBrowserConfig(BaseModel):
      """AD-562: Ship's Records Knowledge Browser (Phases 1-4 OSS)."""
      enabled: bool = False
      max_graph_nodes: int = Field(default=500, ge=0, le=2000)
      max_graph_edges: int = Field(default=1000, ge=0, le=5000)
      jaccard_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
      max_suggestions_per_entry: int = Field(default=5, ge=0, le=50)
      index_refresh_seconds: int = Field(default=300, ge=10, le=3600)
  ```
  Wired on `SystemConfig.knowledge_browser` at `config.py:2918` adjacent to `spatial_explorer: SpatialExplorerConfig`. Default-False per AD-695 transitional precedent — endpoints return 503 until operator flips the switch.

  *New finalize wirer `_wire_knowledge_browser`* in `startup/finalize.py` adjacent to `_wire_spatial_explorer` at `:863`:
  - Sync wirer (no asyncio task creation). Default-False guard. Constructs `KnowledgeBrowserService` from `runtime._records_store` + `getattr(runtime, "_notebook_quality_engine", None)`. Sets `runtime.knowledge_browser`. Returns False if records store unavailable (tier-2 WARNING). Invoked from `finalize_startup` immediately after `_wire_spatial_explorer` invocation at `:3046`.

**HXI surfaces (Phase 1 + 2 + 3 + 4 in one panel):**

  *`ui/src/components/KnowledgeBrowserPanel.tsx`* (~280 LOC):
  - 800×640 floating panel at `top:90 left:90` (offset from SpatialExplorerPanel at `top:80 left:80` to avoid overlap when both open).
  - Header: title `KNOWLEDGE BROWSER` + four view-mode tabs (LIST / READER / GRAPH / TIMELINE) + refresh + close.
  - Three-column body: left filter rail (220px) + center view (variable) + right backlinks rail (240px). Backlinks rail visible only when `knowledgeBrowserSelectedPath` is non-null AND view is `reader`.
  - ESC closes. Mount fetches initial index + entries.
  - Glass styling matches `SpatialExplorerPanel` precedent verbatim (background `rgba(10,10,18,0.85)`, border `1px solid rgba(240,176,96,0.15)`, JetBrains Mono).

  *`ui/src/components/knowledge/EntryListView.tsx`* (~140 LOC):
  - Flat virtualized list (no `react-window` — simple capped render at 200 visible, "… N more" footer) of `knowledgeBrowserEntries` — one row per entry: dept color chip + classification badge + path + author callsign + relative timestamp. Click selects entry, switches view to reader.

  *`ui/src/components/knowledge/EntryReader.tsx`* (~150 LOC):
  - Renders `knowledgeBrowserSelectedDoc` as a minimal-markdown view (custom 30-LOC renderer: line split, `# `/`## ` headings, `**bold**`, `[[wikilink]]` → clickable spans that call `selectKnowledgeBrowserEntry(target)`, fenced code blocks). Frontmatter sidebar shows author, classification, created, updated, revision count, tags. No markdown library dependency.

  *`ui/src/components/knowledge/RecordsGraphView.tsx`* (~180 LOC):
  - `react-force-graph-3d` mount with `nodeColor=(n) => deptColor(n.department)`, `nodeVal=(n) => 1 + Math.log(n.revision_count + 1)`, `linkColor=(l) => l.kind === "suggested" ? "rgba(136,132,168,0.4)" : l.kind === "convergence" ? "#7060a8" : "#f0b060"`, `linkLineDash=(l) => l.kind === "suggested" ? [3,3] : null` (passed via `linkDirectionalParticles` for the dashed-look fallback when force-graph dash isn't supported). Convergence-hub nodes (`is_convergence_hub=true`) get `nodeThreeObject` glow. Click node → `selectKnowledgeBrowserEntry(node.id)` (switches to reader).

  *`ui/src/components/knowledge/TimelineView.tsx`* (~120 LOC):
  - Pure-SVG histogram (raw 0-100 viewBox math, no `getBoundingClientRect`, no chart library — same precedent as `BehavioralMetricsPanel` sparklines per Wave 78). One vertical bar per day bucket, dept-stacked colors. Hover tooltip shows date + total + dept breakdown. Empty state for `total=0`.

  *`ui/src/components/knowledge/BacklinksRail.tsx`* (~110 LOC):
  - Three sections: REFERENCED BY (incoming), REFERENCES (outgoing), SUGGESTED (Jaccard candidates). Each section is a list of clickable path links. Em-dash `—` placeholder for empty sections.

  *`ui/src/components/knowledge/FilterRail.tsx`* (~120 LOC):
  - Five filter chips: AUTHOR (typeahead), DEPARTMENT (chip-list of distinct values), CLASSIFICATION (private/department/ship/fleet toggles), DIRECTORY (chip-list of distinct top-level directories — captains-log/notebooks/duty-logs/convergence-reports/procedures/manuals), DATE RANGE (since/until ISO inputs). Filter-changes call `setKnowledgeBrowserFilters(partial)` → `refreshKnowledgeBrowser()`.

  *`ui/src/components/knowledge/types.ts`* — shared types for the seven components above.

  *Store extensions in `ui/src/store/types.ts` + `ui/src/store/useStore.ts`*:
  - State: `knowledgeBrowserOpen: boolean`, `knowledgeBrowserView: 'list'|'reader'|'graph'|'timeline'`, `knowledgeBrowserSelectedPath: string | null`, `knowledgeBrowserFilters: KnowledgeBrowserFilters`, `knowledgeBrowserEntries: KnowledgeBrowserEntry[]`, `knowledgeBrowserSelectedDoc: KnowledgeBrowserDoc | null`, `knowledgeBrowserBacklinks: KnowledgeBrowserBacklinks | null`, `knowledgeBrowserGraphData: KnowledgeBrowserGraphData | null`, `knowledgeBrowserTimeline: KnowledgeBrowserTimeline | null`, `knowledgeBrowserLoading: boolean`.
  - Actions: `openKnowledgeBrowser()`, `closeKnowledgeBrowser()`, `setKnowledgeBrowserView(view)`, `setKnowledgeBrowserFilters(partial)`, `selectKnowledgeBrowserEntry(path)`, `refreshKnowledgeBrowser()`.

  *`ui/src/App.tsx`*:
  - Import `KnowledgeBrowserPanel`.
  - New `KnowledgeBrowserToggle` component at `top:12 left:410` (next slot after `SpatialExplorerToggle` at `left:340`; verified at `App.tsx:70`). `data-testid="knowledge-browser-toggle"`. Label `RECORDS`.
  - Mount `<KnowledgeBrowserPanel />` adjacent `<SpatialExplorerPanel />`.

**Test plan (~28 pytest + ~32 vitest):**

  *Pytest (`tests/test_ad562_*.py`)*:
  - `test_ad562_backlinks.py` (12 tests): `Reference` + `BacklinkRecord` + `BacklinkIndex` frozen-dataclass round-trip; `extract_references` empty content → `()`; wikilink match (`[[chapel-trust-notes]]`); callsign match (`@chapel`); callsign without prefix (skip false positive `email@x`); frontmatter tags + topic_slug contributions; valid_callsigns filter (unknown `@xyz` not emitted); regex-failure tier-2 log-and-degrade returns `()`; `build_backlink_index` empty entries → empty index; bidirectional fill (A references B → B.referenced_by contains A); duplicate references deduplicated; `suggest_cross_references` Jaccard threshold gating.
  - `test_ad562_records_browse_endpoint.py` (4 tests): happy path with no filters; filters applied (author + department); 503 when `_records_store` None; tier-2 log-and-degrade on store exception → empty list + 200.
  - `test_ad562_records_backlinks_endpoint.py` (4 tests): happy path with explicit + suggested; 404 when path not in index; 503 when `runtime.knowledge_browser` None; `include_suggested=false` excludes suggestions.
  - `test_ad562_records_graph_endpoint.py` (5 tests): happy path with `include_quality=true`; convergence-hub flagging on `convergence-reports/*` entries; max_nodes/max_edges cap honored; 503 when service None; quality overlay attaches when notebook_quality_engine present.
  - `test_ad562_records_timeline_endpoint.py` (2 tests): day bucket dept-stacked; 400 on unsupported bucket value.
  - `test_ad562_finalize_wirer.py` (3 tests): disabled config → returns False, no `runtime.knowledge_browser` slot; enabled + records_store present → `runtime.knowledge_browser` constructed; missing records_store → tier-2 WARNING + False.

  Pytest baseline 12482 → target ≥12510 (+28 floor / +30 stretch). Strict-additive — no existing test modifications.

  *Vitest (`ui/src/__tests__/Ad562*.test.tsx`)*:
  - `Ad562KnowledgeBrowserPanel.test.tsx` (8 tests): renders nothing when closed; opens fetches `/api/records/browse` + `/api/records/graph?include_quality=true`; ESC closes; refresh re-invokes fetches; tab switching changes view; empty state when no entries; loading state; backlinks rail hidden when no selection.
  - `Ad562EntryListView.test.tsx` (5 tests): renders entries with dept color + class badge; click selects + switches view to reader; empty state; "more" footer when entries > 200; classification badge color matches token.
  - `Ad562EntryReader.test.tsx` (5 tests): renders headings + bold + wikilinks; wikilink click calls `selectKnowledgeBrowserEntry`; frontmatter sidebar fields; empty state when no doc selected; raw text fallback when content empty.
  - `Ad562RecordsGraphView.test.tsx` (5 tests): renders force-graph mount; node click calls `selectKnowledgeBrowserEntry`; convergence-hub styling applied; suggested edges dashed style; empty graph state.
  - `Ad562TimelineView.test.tsx` (4 tests): renders bars; dept-stacking renders correct colors; empty state for `total=0`; tooltip on hover (mock via `data-testid` assertion only).
  - `Ad562BacklinksRail.test.tsx` (3 tests): three sections render; em-dash for empty section; click on backlink path calls selector.
  - `Ad562KnowledgeBrowserToggle.test.tsx` (2 tests): renders when closed; hides when open.

  Vitest baseline 393 → target ≥425 (+32 floor / +35 stretch).

**What this AD does NOT change** (out of scope by design):
- No modification of `RecordsStore` (`knowledge/records_store.py`) — read-only consumption only.
- No modification of `NotebooksPanel.tsx` (AD-523b) — preserved as the focused notebook surface; coexists with the unified Knowledge Browser.
- No modification of `SpatialExplorerPanel.tsx` (AD-520) — different graph topology, no shared state.
- No modification of `CognitiveCanvas.tsx` (HXI fragility rule per `.github/copilot-instructions.md`).
- No modification of any existing endpoint in `routers/records.py` — strict-additive append.
- No new EventType.
- No write API (browser is read-only — agents continue to write via `[NOTEBOOK]` blocks per AD-523b precedent).
- No federation cross-instance sync (separate concern).
- No LLM-based reference extraction (regex-based v1; LLM extraction is forcing-function defer if surfaced).
- No native desktop packaging (commercial Phase 5, descriptor-only).
- No bucket value other than "day" in timeline (week/month/year defer if surfaced).
- No virtualization library (`react-window` etc.) — simple cap-and-footer renders at 200 visible entries.
- No new npm dependency.

## DLogs (architect calls)

**DLog #1 — Phase 1 + 2 + 3 + 4 ship together; Phase 5 commercial deferred descriptor-only.** Captain rule: "don't defer unless no choice." Verify-first against HEAD `d8b7c63` confirms zero new dependencies, zero existing-file modifications, all four OSS phases tractable in one Builder cycle (~28 pytest + ~32 vitest). The only deferral is the explicitly-commercial native-packaging surface — which is class-extension territory under the private overlay-repo path token surface and would not consume any further OSS surface area beyond what v1 ships. No FF defer recorded, no GH issue minted.

**DLog #2 — Records-graph-view uses `react-force-graph-3d` (in-tree from AD-611, reused by AD-520).** Spec line 4237 mentions "Three.js + three-forcegraph" as design influence; the in-tree library is `react-force-graph-3d` and v1 sticks with it for graph-engine consistency across HXI surfaces (Memory Graph AD-611, Spatial Explorer AD-520, Knowledge Browser AD-562). Zero new npm packages.

**DLog #3 — Markdown rendering ships as a 30-LOC custom renderer, not a new dependency.** Adding `marked` or `react-markdown` as a new npm dep just to render headings + bold + wikilinks + code blocks is gratuitous package introduction. The custom renderer covers exactly the four cases used in Ship's Records frontmatter+content patterns. If a future record needs full CommonMark parity (tables, inline HTML, footnotes) that's a forcing-function follow-on AD with a real consumer signal.

**DLog #4 — `KnowledgeBrowserService` lives at the bottom of `backlinks.py`, not in a new file.** Spec docks this as a service surface, but it's ~140 LOC and tightly coupled to the helpers above it. Bundling them in one module respects SOLID-Single-Responsibility at the *file* boundary (knowledge-browser concerns) without proliferating files. If the service grows further (e.g., adds federation or multi-tenant indexing), it gets promoted to its own module then.

**DLog #5 — Backlinks rail visible only in reader view.** Filter rail is always visible (left), backlinks rail is conditionally visible (right) only when an entry is selected AND view is `reader`. This avoids dead-weight UI in graph/timeline modes where backlink context is already encoded in the visualization itself.

**DLog #6 — `_notebook_quality_engine` is read with `getattr(runtime, "_notebook_quality_engine", None)` and per-callsign tier-2-log-and-degrade.** AD-555 quality engine may not be running in every operator deployment (it has its own enable flag). The graph endpoint MUST not 503 just because quality data is missing — instead nodes ship with `quality_overlay: null` and the HXI hides the overlay layer.

**DLog #7 — Convergence-hub detection is path-prefix only (no AD-551 service dependency).** Entries whose `path` starts with `"convergence-reports/"` are flagged `is_convergence_hub=true`. The membership edges are derived from frontmatter `contributing_agents` list (an AD-551 frontmatter field). If a deployment has no convergence reports yet, the graph simply has no convergence edges. No runtime dependency on AD-551 service.

## Verified Against Codebase (2026-05-07)

```
HEAD: d8b7c63 (Wave 103 archive)
Pytest baseline: 12482 (Captain stated)
Vitest baseline: 393 (Captain stated)

decisions-era-4-evolution.md:2330: ### AD-562: Ship's Records Knowledge Browser *(2026-04-03)*
decisions-era-4-evolution.md:2337: 3. AD-523c (Ship's Records Dashboard) — planned feature for records browsing. AD-562 supersedes and absorbs this.
decisions-era-4-evolution.md:2350: | AD-562 supersedes AD-523c | ... |
docs/development/roadmap.md:4223: ### Ship's Records Knowledge Browser (AD-562)
docs/development/roadmap.md:4225: AD-562: Ship's Records Knowledge Browser ... (planned, OSS+commercial, depends: AD-434, AD-551, AD-555)
docs/development/roadmap.md:4253: (5) Native App Packaging (commercial)
prompts/archive/WAVE-77-DISPATCH.md:19: AD-523c ... Superseded by AD-562 ... (already closed)

src/probos/knowledge/records_store.py:700: async def read_entry(self, path, reader_id, reader_department=""):
src/probos/knowledge/records_store.py:731: async def list_entries(self, directory="", *, author="", status="", tags=None, classification=""):
src/probos/knowledge/records_store.py:819: async def search(self, query, scope="ship"):
src/probos/knowledge/records_store.py:942: def _parse_document(self, raw):
src/probos/knowledge/knowledge_linter.py:126: def _suggest_cross_references(self, entries):  # reference pattern, NOT reused at runtime in v1

src/probos/routers/records.py:15: router = APIRouter(prefix="/api/records", tags=["records"])
src/probos/routers/records.py:18-131: existing endpoints (stats, documents, documents/{path}, captains-log×2, notebooks/{callsign}×2, search, history/{path})
src/probos/routers/records.py:131: @router.get("/history/{path:path}") — last existing endpoint, INSERTION SITE for new endpoints

src/probos/routers/system.py:353-389: /api/notebook-quality, /api/notebook-quality/history, /api/notebook-quality/agent/{callsign} (AD-555 quality engine surface)

src/probos/config.py:821: class SpatialExplorerConfig(BaseModel):  # AD-520 — INSERTION SITE adjacent for KnowledgeBrowserConfig
src/probos/config.py:834: class MCPAppHostConfig(BaseModel):  # AD-597
src/probos/config.py:1073: class RecordsConfig(BaseModel):  # AD-434 (existing — NOT extended in W104)
src/probos/config.py:2918: spatial_explorer: SpatialExplorerConfig = Field(default_factory=SpatialExplorerConfig)  # AD-520 — INSERTION SITE adjacent for knowledge_browser field

src/probos/startup/finalize.py:863: def _wire_spatial_explorer(*, runtime, config):  # AD-520 — INSERTION SITE adjacent for _wire_knowledge_browser
src/probos/startup/finalize.py:3046: _wire_spatial_explorer(runtime=runtime, config=config)  # invocation site — INSERTION SITE for _wire_knowledge_browser invocation

ui/package.json:19: "react-force-graph-3d": "^1.29.1"  (AD-611 + AD-520 — zero new dep)
ui/src/App.tsx:22: import SpatialExplorerPanel from './components/SpatialExplorerPanel';  # INSERTION SITE for KnowledgeBrowserPanel import
ui/src/App.tsx:58-92: SpatialExplorerToggle component (top:12 left:340)
ui/src/App.tsx:70: top: 12, left: 340  (next slot left:410 for KnowledgeBrowserToggle)
ui/src/App.tsx:92: function BehavioralMetricsToggle()  # toggle pattern reference

ui/src/components/NotebooksPanel.tsx:8-9: Backend: GET /api/records/documents, /api/records/documents/{path}, /api/records/search — pattern reference for fetch wiring
ui/src/components/SpatialExplorerPanel.tsx:1-120: glass styling + ESC + view-mode tabs reference pattern
ui/src/components/BehavioralMetricsPanel.tsx: pure-SVG sparkline pattern reference for TimelineView
```

## Tracking & gates

- **GH issue closed:** #9 (single, cleanly).
- **AD numbers minted:** 0 new (AD-562 pre-allocated at `decisions-era-4-evolution.md:2330` and `roadmap.md:4225`).
- **BF numbers minted:** 0 new.
- **Current highest at HEAD `d8b7c63`:** AD-696, BF-265.
- **Roadmap status flip:** `roadmap.md:4225` `(planned, ...)` → `(Complete v1, OSS+commercial, depends: AD-434, AD-551, AD-555)`.
- **Decisions status flip:** `decisions-era-4-evolution.md:2356` `**Status:** Planned.` → `**Status:** v1 Complete (Wave 104, 2026-05-07). Phases 1+2+3+4 OSS shipped; Phase 5 native packaging remains commercial-tag descriptor-only.`
- **Wave-plan append:** `prompts/wave-plan.yaml` new entry `id: "104"` depends_on `["103"]`, dispatch `prompts/WAVE-104-DISPATCH.md`, prompt `prompts/ad-562-records-knowledge-browser-v1.md`, issues_to_close `[9]`, status `pending`.

## Commercial-leak audit

The literal patterns the pre-commit hook trips on are not used anywhere in this dispatch, the per-AD prompt, or the wave-plan append. The audit table itself uses descriptor-only references (no literal banned text appears in this audit prose):

| Pattern category (descriptor-only) | Hits this wave |
|---|---|
| Three-letter run-rate acronym | 0 |
| Upper-service-tier label | 0 |
| Private overlay-repo path slug | 0 |

The Phase 5 commercial reference uses descriptor-only language: "private overlay-repo path token surface" and "commercial-tag descriptor-only" — neither matches the banned literal patterns. The pre-commit deletion sanity check is unaffected (additive-only wave).

## 4 review passes

**Pass 1 (initial draft):** Wrote dispatch + per-AD prompt + wave-plan append. Reframe sized at four OSS phases in one Builder cycle. Verified all backend dependencies at HEAD: RecordsStore methods, AD-555 quality endpoints, `react-force-graph-3d` in-tree. Confirmed AD-523c already closed in W77.

**Pass 2 (verify-first re-sweep):** Re-ran each anchor against HEAD `d8b7c63`. Confirmed `routers/records.py:131` is `get_record_history` (last existing endpoint — clean append site). Confirmed `config.py:2918` is the `spatial_explorer` field line (clean adjacent insert for `knowledge_browser`). Confirmed `finalize.py:863` is `_wire_spatial_explorer` definition (clean adjacent insert site for `_wire_knowledge_browser`). Confirmed `finalize.py:3046` is the `_wire_spatial_explorer` invocation (clean adjacent insert for invocation). Confirmed `App.tsx:70` is `top: 12, left: 340` for `SpatialExplorerToggle` (next slot `left: 410`).

**Pass 3 (banned-pattern audit + audit-prose self-trip avoidance):** Greppped the dispatch, prompt, and wave-plan append for the three banned literal patterns. Zero hits. The audit table itself uses descriptor-only labels and avoids any literal pattern. Confirmed the Phase 5 commercial carve-out language uses "private overlay-repo path token surface" / "commercial-tag descriptor-only" — neither matches banned literals. (Lesson from W87 P1: the audit prose itself MUST use descriptors only — applied here.)

**Pass 4 (architectural sanity + scope-creep guard):** Caught and corrected three concerns in the initial draft:
- (a) Initial draft had `KnowledgeBrowserService.get_graph()` reading `runtime.bridge_alerts` for Phase 4 quality coloring — this is wrong, AD-555 quality engine is the source. Fixed: reads `_notebook_quality_engine` only, with `getattr(runtime, "_notebook_quality_engine", None)` tier-2 log-and-degrade per agent (DLog #6).
- (b) Initial draft had `convergence-hub` detection reading `runtime.proactive_loop._convergence_history` (private attr, Demeter violation). Fixed: pure path-prefix check on `path.startswith("convergence-reports/")` + frontmatter `contributing_agents` list (DLog #7). Zero runtime dependencies on AD-551 service.
- (c) Initial draft had a new `marked` npm dependency for markdown rendering. Fixed: ship a 30-LOC custom minimal renderer covering the four cases used in Ship's Records (headings, bold, wikilinks, fenced code) — zero new npm deps preserved (DLog #3).
