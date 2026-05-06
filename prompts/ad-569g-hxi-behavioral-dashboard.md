# AD-569g: HXI Behavioral Metrics Dashboard (v1, no facet breakdown)

**Status:** Ready to build
**Type:** New Feature (HXI panel, OSS)
**Scope:** Small-Medium
**Depends on:** AD-569 (BehavioralMetricsEngine — shipped); AD-583f/g (convergence_correctness_rate population — shipped)
**Estimated tests:** **+9 to +12 vitest** (component tests). Pytest delta = 0.
**Prerequisite:** None — backend `/api/behavioral-metrics` and `/api/behavioral-metrics/history` shipped under AD-569 (`src/probos/routers/system.py:299-326`).

## Problem

`BehavioralMetricsEngine` has shipped with five behavioral metrics (Frame Diversity, Synthesis Detection, Cross-Department Trigger Rate, Convergence Correctness, Anchor-Grounded Emergence) and a Dream Step 13 update cycle. Two REST endpoints expose the data:

- `GET /api/behavioral-metrics` — latest snapshot
- `GET /api/behavioral-metrics/history?limit=20` — rolling history

The HXI has zero surface for these metrics. The Captain has no way to see whether collaborative intelligence is happening on the ship, whether convergences are actually correct, whether departments are triggering each other's investigations, or how these signals trend over time. The metrics are computed and stored — they're invisible.

This prompt builds **AD-569g v1** — a read-only floating dashboard panel surfacing the existing snapshot data. It does **not** ship facet breakdown / variance decomposition (those depend on AD-569f's psychometric framework which is deferred).

## Solution

One floating panel `BehavioralMetricsPanel.tsx` modeled on `NotebooksPanel.tsx` (AD-523b, the most recently shipped HXI panel). Backend zero-touch — only consumes existing endpoints. HXI-only delivery, identical pattern to AD-523b's Wave 77 build.

The panel surfaces:

1. **Five metric tiles** — one per behavioral metric with the latest score (0-1), a label, and a one-line definition tooltip. Color-coded by metric domain:
   - Frame Diversity (analytical lenses) — teal `#50b0a0`
   - Synthesis Detection (emergent insights) — amber `#f0b060`
   - Cross-Dept Trigger (silo-breaking) — violet `#a070d0`
   - Convergence Correctness (verified accuracy) — green `#70c080` (shows "—" when `convergence_correctness_rate` is `null`)
   - Anchor-Grounded Emergence (provenance-validated) — gold `#d0a030`
2. **Composite quality score** — single prominent reading of `behavioral_quality_score` (0-1) at the panel header.
3. **Rolling sparklines** — 20-point time series per metric, pulled from `/api/behavioral-metrics/history`. Pure SVG polyline, no chart library. Empty-state: dashed baseline.
4. **Last-update timestamp** — relative ("2h ago") + ISO tooltip.
5. **Empty state** — when engine reports `status: "not_available"` or `"no_data"`, render a clean explanation panel ("Behavioral metrics will appear after the first dream cycle (Step 13)").
6. **No facet breakdown** — explicit deferral note in the panel footer: "Facet breakdown (department × stimulus × occasion) lands with AD-569f."

Toggle button `METRICS` follows the inline-toggle pattern from `App.tsx:22-54` (NotebooksToggle).

## Verified Against Codebase (2026-05-06, HEAD `7bd1980`)

```
git rev-parse HEAD
  7bd19806b7a01957fa01c24d99434ec4d428dd3f

# Backend endpoints (shipped, zero-touch in this prompt):
src/probos/routers/system.py:18  router = APIRouter(prefix="/api", tags=["system"])
src/probos/routers/system.py:299-309  @router.get("/behavioral-metrics") → engine.latest_snapshot.to_dict()
src/probos/routers/system.py:311-326  @router.get("/behavioral-metrics/history") → snapshots[-limit:]
src/probos/cognitive/behavioral_metrics.py:35-77  BehavioralSnapshot fields (12 metric fields + behavioral_quality_score + 4 aggregate)
src/probos/cognitive/behavioral_metrics.py:79-101  BehavioralMetricsEngine class

# HXI panel template (AD-523b, just shipped Wave 77):
ui/src/components/NotebooksPanel.tsx:1-70  floating panel pattern; useStore selectors; useEffect open-trigger fetch
ui/src/App.tsx:20  import NotebooksPanel from './components/NotebooksPanel';
ui/src/App.tsx:22-54  inline NotebooksToggle() pattern (zIndex 25, top:12 left:200 — DASHBOARD will use top:12 left:270)
ui/src/App.tsx:170-171  <NotebooksPanel /> + <NotebooksToggle /> mount points
ui/src/store/useStore.ts:267-274  notebooksOpen, notebooksLoading, … state shape template
ui/src/store/useStore.ts:319-320  openNotebooks, closeNotebooks action signatures
ui/src/store/useStore.ts:574-613  openNotebooks/closeNotebooks implementations (fetch + set pattern)
ui/src/__tests__/NotebooksPanel.test.tsx:5,30  describe('NotebooksPanel (AD-523b)', …) — vitest+RTL pattern

# Vitest test directory:
ui/src/__tests__/  (existing test directory; new file lands here)
```

Every concrete claim above maps to the live codebase at HEAD `7bd1980`. Phantom-API risk: **0**.

## Implementation

### Section 1: Store state + actions

**File:** `ui/src/store/useStore.ts`

Add to the `BridgeState` interface near the existing `notebooksLoading` group (around line 274):

```typescript
  // AD-569g: Behavioral Metrics Dashboard
  behavioralMetricsOpen: boolean;
  behavioralMetricsLoading: boolean;
  behavioralMetricsLatest: BehavioralSnapshot | null;
  behavioralMetricsHistory: BehavioralSnapshot[];
  behavioralMetricsError: string | null;
```

Add to the actions interface near `closeNotebooks` (around line 320):

```typescript
  openBehavioralMetrics: () => Promise<void>;
  closeBehavioralMetrics: () => void;
  refreshBehavioralMetrics: () => Promise<void>;
```

Add the type definition (top of `useStore.ts` or in `ui/src/store/types.ts` next to other shared types — Builder picks the existing location):

```typescript
export interface BehavioralSnapshot {
  timestamp: number;
  frame_diversity_score: number;
  frame_diversity_threads: number;
  department_representation: Record<string, number>;
  synthesis_rate: number;
  synthesis_threads: number;
  total_novel_elements: number;
  cross_dept_trigger_rate: number;
  trigger_pairs: Array<[string, string, number]>;
  trigger_events: number;
  convergence_events: number;
  verified_correct: number;
  verified_incorrect: number;
  unverified: number;
  convergence_correctness_rate: number | null;
  anchor_grounded_rate: number;
  anchor_independence_score: number;
  anchor_analyzed_threads: number;
  threads_analyzed: number;
  behavioral_quality_score: number;
}
```

Add to the initial state object near `notebooksOpen: false` (around line 500-507):

```typescript
  behavioralMetricsOpen: false,
  behavioralMetricsLoading: false,
  behavioralMetricsLatest: null,
  behavioralMetricsHistory: [],
  behavioralMetricsError: null,
```

Add the actions near `openNotebooks` (around line 574-613). Both endpoints can return `{status: "not_available"}` or `{status: "no_data"}` envelopes — handle both paths:

```typescript
  openBehavioralMetrics: async () => {
    set({ behavioralMetricsOpen: true, behavioralMetricsLoading: true, behavioralMetricsError: null });
    await get().refreshBehavioralMetrics();
  },

  closeBehavioralMetrics: () =>
    set({ behavioralMetricsOpen: false }),

  refreshBehavioralMetrics: async () => {
    set({ behavioralMetricsLoading: true, behavioralMetricsError: null });
    try {
      const [latestRes, historyRes] = await Promise.all([
        fetch('/api/behavioral-metrics').then(r => r.json()),
        fetch('/api/behavioral-metrics/history?limit=20').then(r => r.json()),
      ]);
      const latest =
        latestRes && latestRes.status !== 'not_available' && latestRes.status !== 'no_data'
          ? (latestRes as BehavioralSnapshot)
          : null;
      const history =
        historyRes && Array.isArray(historyRes.snapshots)
          ? (historyRes.snapshots as BehavioralSnapshot[])
          : [];
      set({
        behavioralMetricsLatest: latest,
        behavioralMetricsHistory: history,
        behavioralMetricsLoading: false,
      });
    } catch (err) {
      set({
        behavioralMetricsLatest: null,
        behavioralMetricsHistory: [],
        behavioralMetricsLoading: false,
        behavioralMetricsError: err instanceof Error ? err.message : 'Failed to fetch behavioral metrics',
      });
    }
  },
```

### Section 2: Component

**File:** `ui/src/components/BehavioralMetricsPanel.tsx` (NEW)

Mirror `NotebooksPanel.tsx` structure: floating panel, ESC-to-close, header with composite score, body with 5 metric tiles each containing a score + sparkline, footer with last-update timestamp + AD-569f note.

Builder writes the full component. Required interface elements:
- Hidden when `!behavioralMetricsOpen`. Returns `null` early.
- Header: composite `behavioral_quality_score` (formatted as percentage), close button (`×` Unicode multiplication sign — same as `NotebooksPanel`).
- Five metric tiles in a 2-column grid (Frame Diversity, Synthesis Detection, Cross-Dept Trigger, Convergence Correctness, Anchor-Grounded Emergence). Each tile:
  - Metric name (uppercase, fontFamily `'JetBrains Mono'`).
  - Score (large, formatted to 2 decimals; "—" if `convergence_correctness_rate === null`).
  - SVG sparkline pulling from `behavioralMetricsHistory.map(s => s[<metric_field>])`. Empty array → render dashed `M0,h L100,h` baseline.
  - One-line description as a `title` attribute (HTML tooltip, no JS popovers needed).
- Empty state: when `behavioralMetricsLatest === null && !behavioralMetricsLoading`, render a centered `<div>` with text:
  > "Behavioral metrics will appear after the first dream cycle (Step 13)."
- Loading state: when `behavioralMetricsLoading && !behavioralMetricsLatest`, render text "Computing behavioral metrics…".
- Error state: when `behavioralMetricsError`, render the error string in dim red `#a04848`.
- Footer:
  > "Facet breakdown (department × stimulus × occasion) lands with AD-569f."
- Refresh button (optional, "↻" Unicode arrow — keep glyph stroke-only, no emoji): triggers `refreshBehavioralMetrics()`.

**HXI Design Principles compliance:**
- All glyphs are inline SVG (`strokeWidth: 1.5`, `strokeLinecap: 'round'`) or Unicode characters from the existing `NotebooksPanel` palette (`×` close, `↻` refresh). NO emoji (HXI Design Principle #3).
- Color palette amber/blue/violet trust spectrum (per principle #2).
- Motion: subtle 1.5s pulse on the composite quality score during refresh (`opacity` keyframe animation).
- Department-colored representation: the `department_representation` field is informational; in v1 just render as a small chip strip below the Frame Diversity tile.

**File:** `ui/src/__tests__/BehavioralMetricsPanel.test.tsx` (NEW)

Test plan (vitest + @testing-library/react). Mirror `NotebooksPanel.test.tsx` mocking pattern (mock `fetch`, exercise store actions through component render):

1. `test_renders_nothing_when_closed` — when `behavioralMetricsOpen: false`, panel does not render.
2. `test_opens_and_fetches` — calling `openBehavioralMetrics()` triggers two fetches (`/api/behavioral-metrics`, `/api/behavioral-metrics/history?limit=20`).
3. `test_renders_five_metric_tiles_when_data_present` — five tiles with the labels Frame Diversity, Synthesis, Cross-Dept Trigger, Convergence Correctness, Anchor-Grounded Emergence.
4. `test_renders_composite_quality_score` — header shows formatted percentage of `behavioral_quality_score`.
5. `test_renders_empty_state_when_not_available` — `{status: "not_available"}` from latest endpoint shows "Behavioral metrics will appear after the first dream cycle".
6. `test_renders_empty_state_when_no_data` — `{status: "no_data"}` from latest endpoint shows the same empty-state copy.
7. `test_renders_em_dash_for_null_convergence_correctness` — when `convergence_correctness_rate: null`, that tile renders "—" (not "0.00").
8. `test_close_button_closes_panel` — clicking close sets `behavioralMetricsOpen: false`.
9. `test_renders_error_state` — when fetch rejects, panel shows the error message and does not crash.
10. *(Optional)* `test_sparkline_renders_polyline_when_history_present` — SVG `polyline` element appears for at least one tile when `behavioralMetricsHistory` has 3+ entries.
11. *(Optional)* `test_sparkline_renders_baseline_when_history_empty` — SVG `path` with dashed stroke appears when history is empty.

Floor: 9 tests. Builder may add 1-3 more boundary cases (history limit edge cases, refresh-button click) up to ~+12 total.

### Section 3: App.tsx mount + inline toggle

**File:** `ui/src/App.tsx`

Add the import next to NotebooksPanel (around line 20):

```typescript
import BehavioralMetricsPanel from './components/BehavioralMetricsPanel';
```

Add the inline toggle component near `NotebooksToggle()` (after line 54, before `CrewRosterToggle`). Use `top: 12, left: 270` to sit to the right of NOTEBOOKS (which is at left:200):

```typescript
function BehavioralMetricsToggle() {
  const open = useStore(s => s.behavioralMetricsOpen);
  const openMetrics = useStore(s => s.openBehavioralMetrics);

  if (open) return null;

  return (
    <div
      onClick={() => openMetrics()}
      data-testid="behavioral-metrics-toggle"
      style={{
        position: 'fixed',
        top: 12, left: 270,
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
      METRICS
    </div>
  );
}
```

Mount the panel + toggle inside the JSX root (around lines 168-171, next to `NotebooksPanel`):

```tsx
      <NotebooksPanel />
      <NotebooksToggle />
      <BehavioralMetricsPanel />
      <BehavioralMetricsToggle />
```

### Section 4: Tracking updates

**File:** `PROGRESS.md`

Add Wave 78 entry at the top of the era-4 progress block, summarizing the resolution:

> Wave 78 close: AD-569 Behavioral Metrics Extensions — 5 verify-only (a/b/c/d/e shipped via AD-569 main + AD-583f/g) + 1 build (569g v1 HXI Behavioral Dashboard) + 1 deferral with forcing function (569f Psychometric Framework). HXI-only delivery on top of `/api/behavioral-metrics` (shipped under AD-569). 569f deferred until first qualification probe consumer requires variance decomposition. Issue #108.

**File:** `docs/development/roadmap.md`

The 569 series is already marked `*(complete)*` at line 4394. Update only the deferred sub-AD bullets (lines 4501-4507):

- Line 4501-4505 (`569a` through `569e`): tag each with `*(complete)*` (or `*(complete via AD-583f/g)*` for 569d). Preserve the descriptive text.
- Line 4506 (`569f`): tag `*(deferred — forcing function: first qualification probe requiring G-theory variance decomposition; tracked under AD-569 umbrella)*`.
- Line 4507 (`569g`): tag `*(complete — Wave 78, v1 without facet breakdown)*`.

**File:** `prompts/wave-plan.yaml`

Append id `"78"` entry per the dispatch's Captain workflow.

## Tests

Run inside `ui/`:

```
cd ui && npx vitest run
```

Expected: existing vitest tests pass + 9-12 new `BehavioralMetricsPanel.test.tsx` tests pass.

Run pytest full gate:

```
pytest tests/ -q -n 4 --dist=loadfile
```

Expected: **11498 collected, 11498 passed** (Δ vs baseline = 0). No new pytest tests.

## What This Does NOT Change

1. **No backend changes.** Zero modifications under `src/probos/`. The `/api/behavioral-metrics` endpoints are read-only consumers of `BehavioralMetricsEngine`, both shipped under AD-569.
2. **No new pytest tests.** Backend is verify-only this wave.
3. **No facet breakdown / variance decomposition.** That's AD-569f — explicitly deferred.
4. **No emergence panel.** AD-557 emergence dashboard is a separate (unbuilt) deferred surface; not in scope.
5. **No new chart library.** Sparklines are SVG `polyline`/`path` only.
6. **No write surface.** Captain reads metrics; the engine writes them via Dream Step 13.
7. **No emoji.** All glyphs are inline SVG or Unicode geometric characters (`×`, `↻`).
8. **No commercial gating.** Panel is free-tier OSS, no paywall, no enterprise SKU language.
9. **No changes to AD-557 EmergenceMetrics** or its API endpoints.
10. **No changes to `BehavioralMetricsConfig`** or to the engine's snapshot schema.
11. **No `IntentMessage` / `BaseAgent` protocol changes** (HXI-only, no Python protocol surface).
12. **No new event types.** No `BEHAVIORAL_METRICS_VIEWED` or similar — read endpoint, no events.

## Acceptance Criteria

1. `git status` (post-Builder) shows exactly:
   - `M ui/src/store/useStore.ts`
   - `M ui/src/store/types.ts` *(only if Builder picks types.ts as the BehavioralSnapshot home; otherwise the type lives in useStore.ts and types.ts is untouched)*
   - `M ui/src/App.tsx`
   - `?? ui/src/components/BehavioralMetricsPanel.tsx` (new)
   - `?? ui/src/__tests__/BehavioralMetricsPanel.test.tsx` (new)
   - `M PROGRESS.md`
   - `M docs/development/roadmap.md`
   - `M prompts/wave-plan.yaml`
   No other files. No `src/probos/` modifications. No new pytest files.
2. **Vitest gate** `cd ui && npx vitest run` — new `BehavioralMetricsPanel.test.tsx` reports **9-12 passing**; no pre-existing vitest test fails.
3. **Pytest full gate** `pytest tests/ -q -n 4 --dist=loadfile` — **11498 collected, 11498 passed** (matching baseline). Δ = 0.
4. PROGRESS.md Wave 78 entry summarizes a/b/c/d/e/f/g resolution in one paragraph (close-as-shipped, build, defer-with-forcing-function).
5. roadmap.md AD-569 deferred bullets each tagged with appropriate completeness/deferral status.
6. wave-plan.yaml id `"78"` entry committed.
7. GH #108 closed with verify-first evidence + commit hash + sub-AD-by-sub-AD resolution table.
8. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`** — specifically: HXI emoji prohibition; SOLID-S (panel does only display + refresh, no write surface); Liskov (BehavioralSnapshot type matches backend `BehavioralSnapshot.to_dict()` contract); type annotations on all exported interfaces; no fire-and-forget tasks (the `Promise.all` is awaited); SVG-only icons (no emoji); no private-attribute access across module boundaries.
9. No commercial language, pricing, or revenue references in any artifact (panel copy, dispatch, prompt body, roadmap entry).
