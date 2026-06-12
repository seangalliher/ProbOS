# AD-944 — Migrate the top toolbar into command stations, retire it (Bridge as Ship's Computer)

**Target repo:** OSS (`d:\ProbOS`). **This AD = AD-944.** GitHub epic `seangalliher/ProbOS#873`; this issue `#879`.
**Mode:** Builder. Frontend only (UI). Commit local. **No push** (the Captain decides the push).
**Builds on:** AD-943 (commit `d373501b`) — the typed `CommandStation` model + registry. **Epic siblings (DO NOT
build — awareness only):** `#880` AD-945 (fold the bottom-right 4-toggle cluster into a station config), `#881`
AD-946 (Ship's-Computer command palette in the omnibox).

## Goal
Migrate every item in the top-center `role="toolbar"` ("HXI panels") app-launcher in `ui/src/App.tsx` into the
appropriate AD-943 command station as a `StationAction`, **add the station-action rendering that AD-943 modelled
but did not yet draw**, then **REMOVE the top toolbar entirely**. This is the **first VISIBLE change of the
epic**: after it the 9-button app-launcher is gone, and those nine destinations open from Bridge stations.

The `personnel`, `science`, and `command` stations — empty placeholders in AD-943, hidden by `isPopulated` —
gain their launch actions here and therefore **start rendering**. `communications` gains two launch actions on
top of its existing body/config. `operations` and `engineering` keep their AD-943 bodies unchanged (no toolbar
item maps to them).

## Why
AD-943 built the typed slot (`StationAction { id, label, onInvoke, count? }`) and left `actions: []` on every
station, **and BridgePanel renders only `body` + `config`, never `actions`** (verified below). AD-944 is the
data-edit + render wave the model was built for: fill the action slots and draw them. The Bridge is the single
modern Ship's-Computer control surface (NOT an agent — AD-398); the launcher belongs there as browseable
stations, with AD-946's omnibox as the later keyboard-fast path. Reference: `docs/design/hxi-glass-bridge.md`
(Zone-4 "not an app launcher"); the 11 HXI Design Principles in `.github/copilot-instructions.md`.

---

## Verified current shape (grep evidence in the footer)

**BridgePanel does NOT render `actions` today.** The registry map at `BridgePanel.tsx:178`→`197` draws only the
body and config:
```tsx
{buildBridgeStations({ dmChannelCount: dmChannels.length, kanbanCount: kanbanTasks.length })
  .filter(isPopulated)
  .map(st => (
    <BridgeSection key={st.id} stationId={st.id} title={st.title} count={st.count ?? 0}
      defaultOpen={st.defaultOpen} accentColor={st.accent} onExpand={st.onExpand}>
      {st.body?.()}
      {st.config.map(c => (<div key={c.id}>{c.render()}</div>))}
    </BridgeSection>
  ))}
```
→ **AD-944 MUST add an `st.actions` render block here** (Section 2). Without it, filling `actions` would change
nothing on screen.

**The toolbar (the AD-944 target) is `App.tsx:34`→`164` + the `<TopNav />` mount at `:241`.** `function TopNav()`
(`:101`) returns the `<div role="toolbar" aria-label="HXI panels">` (`:131`→`162`) holding 9 `NavButton`s, 2
`NavSeparator`s, and `<CommercialOverlayBadge />` (`:161`). `NavButton` (`:48`), `NavSeparator` (`:89`), and the
`NavButtonProps` interface (`:40`) are defined in `App.tsx` and **used nowhere else** (footer grep) → dead code
after removal.

**The 9 toolbar items → their REAL store actions (all verified):**

| Toolbar label | testId (preserve) | store action | store | line | sync/async |
|---|---|---|---|---|---|
| WARD ROOM | *(none)* | `openWardRoom` (+ `totalUnread` badge) | `useStore` | `550`/`1389` | **async** |
| CREW | *(none)* | `openCrewManifest` (App alias `openCrew`, `:108`) | `useStore` | `516`/`1008` | **async** |
| PERSONNEL | `personnel-toggle` | `openPersonnelConsole` | `useStore` | `563`/`1483` | sync |
| CHATS | `chats-toggle` | `openChats` | `useStore` | `529`/`1087` | sync |
| NOTEBOOKS | `notebooks-toggle` | `openNotebooks` | `useStore` | `521`/`1040` | **async** |
| RECORDS | `knowledge-browser-toggle` | `openKnowledgeBrowser` | `useStore` | `543`/`1211` | **async** |
| EXPLORER | `spatial-explorer-toggle` | `openSpatialExplorer` | `useStore` | `536`/`1204` | sync |
| METRICS | `behavioral-metrics-toggle` | `openBehavioralMetrics` | `useStore` | `532`/`1169` | **async** |
| SETTINGS | `topnav-settings` | `openSettings` | **`useSettingsStore`** | `59`/`134` | **async** |

`totalUnread` = `Object.values(wardRoomUnread).reduce((s,n)=>s+n,0)` (the `App.tsx:104` pattern; `wardRoomUnread`
is a store slice). `openSettings` is in a **different store** (`useSettingsStore`) and sets `open:true`
**synchronously** at the top of its body (`useSettingsStore.ts:138`) before the await. Async actions were
called `() => { void openX(); }` in the toolbar (`App.tsx:154`,`:159`) — preserve that void-wrap.

**`CommercialOverlayBadge`** (`ui/src/components/CommercialOverlayBadge.tsx`) — `data-testid="commercial-overlay-badge"`,
returns `null` unless a commercial overlay is loaded (the default OSS build never shows it), and has **no own
positioning** (it relied on the toolbar's flex). Its **only importer is `App.tsx`** (footer grep). It MUST be
re-mounted so it stays in the tree (Section 3).

**No test renders `<App>` or asserts on the toolbar / `"HXI panels"` / `NavButton` / `TopNav`** (footer grep) →
removing the toolbar breaks no test. The factory's blast radius is `BridgePanel.tsx` (call site) +
`stations.test.tsx` (the only test importer); `IntentSurface.tsx:875` mounts `<BridgePanel>` with unchanged
props.

---

## The decision — station → action placement

| Station | Migrated launches (in order) | accent (unchanged) | notes |
|---|---|---|---|
| **communications** | Ward Room (`count = totalUnread`), Chats | `#b080d0` | keeps its AD-943 body (THREADS) + config (comms admin) + `onExpand` (Ward Room) |
| **personnel** | Crew, Personnel, Metrics | `#50b0a0` | was an empty placeholder → now populated → **now renders** |
| **science** | Notebooks, Records, Explorer | `#5090d0` | was an empty placeholder → now populated → **now renders** |
| **command** | Settings | `#f0b060` | was an empty placeholder → now populated → **now renders** |
| operations | *(none)* | `#d0a030` | unchanged — keeps the kanban body |
| engineering | *(none)* | `#70a0d0` | unchanged — keeps the services body |

2 + 3 + 3 + 1 = **all 9 toolbar items**, mapped onto the 6-station taxonomy. **Intentional, not a bug:** the
Ward Room launch appears BOTH as the communications station's `onExpand` (the header Expand glyph, AD-943) AND as
a labelled action row — the action row is what carries the live `totalUnread` badge (the Expand glyph cannot).

**Bridge open/close behavior is unchanged.** Invoking a station action just calls the existing `open*` action
(exactly what the toolbar button did) — it does NOT close the Bridge, mirroring the prior toolbar (which never
touched `bridgeOpen`). Do not add any Bridge-close side effect to the actions.

**`defaultOpen` stays `false`** for every station (the AD-943 convention; progressive disclosure — HXI #5). The
Captain opens the Bridge, expands a station, clicks a launch; the omnibox fast-path is AD-946.

---

## Files

### Section 1 — MODIFY: `ui/src/components/bridge/stations.tsx`
Extend the factory `ctx` with `totalUnread`, import the second store, and **fill the four stations' `actions`
arrays**. The `onInvoke` closures reach the singleton stores via `getState()` — the idiomatic Zustand pattern and
consistent with AD-943's `onExpand: () => useStore.setState({...})`. Async actions are `void`-wrapped.

**1a. Add the `useSettingsStore` import.** After the existing `useStore` import:
```
SEARCH:
import type { ReactNode } from 'react';
import { useStore } from '../../store/useStore';
import { BridgeSystem, BridgeThreads } from './BridgeSystem';

REPLACE:
import type { ReactNode } from 'react';
import { useStore } from '../../store/useStore';
import { useSettingsStore } from '../../store/useSettingsStore';
import { BridgeSystem, BridgeThreads } from './BridgeSystem';
```

**1b. Extend the factory signature with `totalUnread`.**
```
SEARCH:
export function buildBridgeStations(ctx: {
  dmChannelCount: number;
  kanbanCount: number;
}): CommandStation[] {
  const m = STATION_META;

REPLACE:
export function buildBridgeStations(ctx: {
  dmChannelCount: number;
  kanbanCount: number;
  totalUnread: number;
}): CommandStation[] {
  const m = STATION_META;
```

**1c. Fill the `communications` action slot** (it already has body + config + onExpand — add `actions`):
```
SEARCH:
      actions: [],
      config: [
        { id: 'comms-admin', label: 'Communications', render: () => <BridgeCommunications /> },
      ],
    },

REPLACE:
      actions: [
        // The Ward Room launch carries the live unread badge the header Expand cannot.
        { id: 'ward-room-action', label: 'Ward Room', count: ctx.totalUnread,
          onInvoke: () => { void useStore.getState().openWardRoom(); } },
        { id: 'chats-toggle', label: 'Chats',
          onInvoke: () => useStore.getState().openChats() },
      ],
      config: [
        { id: 'comms-admin', label: 'Communications', render: () => <BridgeCommunications /> },
      ],
    },
```

**1d. Fill the `personnel` placeholder** (preserve `data-testid` on the testId-bearing items):
```
SEARCH:
    {
      id: 'personnel',
      title: m.personnel.title, accent: m.personnel.accent,
      defaultOpen: false, actions: [], config: [],
    },

REPLACE:
    {
      id: 'personnel',
      title: m.personnel.title, accent: m.personnel.accent,
      defaultOpen: false,
      actions: [
        { id: 'crew-action', label: 'Crew',
          onInvoke: () => { void useStore.getState().openCrewManifest(); } },
        { id: 'personnel-toggle', label: 'Personnel',
          onInvoke: () => useStore.getState().openPersonnelConsole() },
        { id: 'behavioral-metrics-toggle', label: 'Metrics',
          onInvoke: () => { void useStore.getState().openBehavioralMetrics(); } },
      ],
      config: [],
    },
```

**1e. Fill the `science` placeholder:**
```
SEARCH:
    {
      id: 'science',
      title: m.science.title, accent: m.science.accent,
      defaultOpen: false, actions: [], config: [],
    },

REPLACE:
    {
      id: 'science',
      title: m.science.title, accent: m.science.accent,
      defaultOpen: false,
      actions: [
        { id: 'notebooks-toggle', label: 'Notebooks',
          onInvoke: () => { void useStore.getState().openNotebooks(); } },
        { id: 'knowledge-browser-toggle', label: 'Records',
          onInvoke: () => { void useStore.getState().openKnowledgeBrowser(); } },
        { id: 'spatial-explorer-toggle', label: 'Explorer',
          onInvoke: () => useStore.getState().openSpatialExplorer() },
      ],
      config: [],
    },
```

**1f. Fill the `command` placeholder** (Settings lives in `useSettingsStore`):
```
SEARCH:
    {
      id: 'command',
      title: m.command.title, accent: m.command.accent,
      defaultOpen: false, actions: [], config: [],
    },

REPLACE:
    {
      id: 'command',
      title: m.command.title, accent: m.command.accent,
      defaultOpen: false,
      actions: [
        { id: 'topnav-settings', label: 'Settings',
          onInvoke: () => { void useSettingsStore.getState().openSettings(); } },
      ],
      config: [],
    },
```

> `isPopulated` is unchanged — it already returns `true` when `actions.length > 0`, so personnel/science/command
> now pass the `.filter(isPopulated)` and render. No edit to `isPopulated`.

### Section 2 — MODIFY: `ui/src/components/BridgePanel.tsx`
Add a `StationActionRow` presentational component, render `st.actions` in the registry map, and compute +
thread `totalUnread`.

**2a. Import the `StationAction` type** (extend the existing stations import):
```
SEARCH:
import { buildBridgeStations, isPopulated, type StationId } from './bridge/stations';

REPLACE:
import { buildBridgeStations, isPopulated, type StationId, type StationAction } from './bridge/stations';
```

**2b. Add a co-located `StationActionRow`** (a launch row matching the BridgeSection child aesthetic —
stroke-SVG glyph, uppercase mono, optional amber count pill; NO emoji per HXI #3). Insert immediately AFTER the
`BridgeSection` function's closing brace and BEFORE `export function BridgePanel`:
```
SEARCH:
      {open && <div style={{ padding: '4px 8px 8px' }}>{children}</div>}
    </div>
  );
}

export function BridgePanel({ open, onClose }: { open: boolean; onClose: () => void }) {

REPLACE:
      {open && <div style={{ padding: '4px 8px 8px' }}>{children}</div>}
    </div>
  );
}

/* ── Station launch row (AD-944) — a discrete "open destination" item migrated
   from the retired top toolbar. Stroke-SVG glyph, uppercase mono, optional amber
   unread pill; NO emoji (HXI #3). data-testid mirrors the old toolbar testIds so
   existing specs keep resolving. ── */
function StationActionRow({ action, accent }: { action: StationAction; accent: string }) {
  return (
    <div
      data-testid={action.id}
      onClick={action.onInvoke}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '5px 6px',
        cursor: 'pointer',
        userSelect: 'none' as const,
        borderRadius: 4,
      }}
    >
      <span style={{ color: '#666' }}><ChevronRight size={8} /></span>
      <span style={{
        fontSize: 10, fontWeight: 700, letterSpacing: 1.5,
        textTransform: 'uppercase' as const, color: accent,
      }}>
        {action.label}
      </span>
      {typeof action.count === 'number' && action.count > 0 && (
        <span style={{
          marginLeft: 'auto',
          background: '#f0b060', color: '#0a0a12',
          borderRadius: 8, padding: '1px 6px', fontSize: 9, fontWeight: 700,
        }}>{action.count}</span>
      )}
    </div>
  );
}

export function BridgePanel({ open, onClose }: { open: boolean; onClose: () => void }) {
```
> `ChevronRight` is already imported (`BridgePanel.tsx:3`). No new glyph import.

**2c. Read `wardRoomUnread` + compute `totalUnread`** inside `BridgePanel` (next to the other selectors):
```
SEARCH:
  const dmChannels = useStore(s => s.wardRoomDmChannels);
  const refreshDms = useStore(s => s.refreshWardRoomDmChannels);

  useEffect(() => { refreshDms(); }, [refreshDms]);

REPLACE:
  const dmChannels = useStore(s => s.wardRoomDmChannels);
  const refreshDms = useStore(s => s.refreshWardRoomDmChannels);
  const wardRoomUnread = useStore(s => s.wardRoomUnread);
  const totalUnread = Object.values(wardRoomUnread ?? {}).reduce((sum, n) => sum + n, 0);

  useEffect(() => { refreshDms(); }, [refreshDms]);
```

**2d. Render `st.actions` + pass `totalUnread`** into the factory map:
```
SEARCH:
        {buildBridgeStations({
          dmChannelCount: dmChannels.length,
          kanbanCount: kanbanTasks.length,
        })
          .filter(isPopulated)
          .map(st => (
            <BridgeSection
              key={st.id}
              stationId={st.id}
              title={st.title}
              count={st.count ?? 0}
              defaultOpen={st.defaultOpen}
              accentColor={st.accent}
              onExpand={st.onExpand}
            >
              {st.body?.()}
              {st.config.map(c => (
                <div key={c.id}>{c.render()}</div>
              ))}
            </BridgeSection>
          ))}

REPLACE:
        {buildBridgeStations({
          dmChannelCount: dmChannels.length,
          kanbanCount: kanbanTasks.length,
          totalUnread,
        })
          .filter(isPopulated)
          .map(st => (
            <BridgeSection
              key={st.id}
              stationId={st.id}
              title={st.title}
              count={st.count ?? 0}
              defaultOpen={st.defaultOpen}
              accentColor={st.accent}
              onExpand={st.onExpand}
            >
              {st.actions.map(a => (
                <StationActionRow key={a.id} action={a} accent={st.accent} />
              ))}
              {st.body?.()}
              {st.config.map(c => (
                <div key={c.id}>{c.render()}</div>
              ))}
            </BridgeSection>
          ))}
```

### Section 3 — MODIFY: `ui/src/App.tsx` — remove the toolbar, re-mount the badge

**3a. Delete the entire top-navigation block.** Remove `App.tsx:34`→`164` — the `// ── Top navigation ──`
comment, the `NavButtonProps` interface, `NavButton`, `NavSeparator`, and the whole `TopNav` function (which
contains the `<div role="toolbar" aria-label="HXI panels">` cluster and the `<CommercialOverlayBadge />`). The
deletion span starts at the line:
```
// ── Top navigation ───────────────────────────────────────────────
```
and ends at the closing brace of `TopNav` (the line immediately before `export default function App() {`).
Replace the whole span with a single marker comment:
```
// AD-944: the top-center "HXI panels" toolbar was retired — its nine launches
// now live in the Bridge command stations (communications / personnel / science /
// command). See ui/src/components/bridge/stations.tsx.
```

**3b. Replace the `<TopNav />` mount with the re-homed badge.** The badge must stay in the tree (invisible by
default; it self-hides when no commercial overlay is loaded). Give it a minimal `position: fixed` home in the
top-left band the toolbar vacated (reusing the toolbar's `zIndex: 25`):
```
SEARCH:
      <CameraLiveIndicator />
      <CameraPreviewPanel />
      <TopNav />
      <WelcomeOverlay />

REPLACE:
      <CameraLiveIndicator />
      <CameraPreviewPanel />
      {/* AD-944: the commercial-overlay status badge outlived the retired toolbar.
          It is invisible in the default OSS build (renders null when no overlay is
          loaded) but must stay mounted. Re-homed to the vacated top-left band. */}
      <div style={{ position: 'fixed', top: 12, left: 12, zIndex: 25 }}>
        <CommercialOverlayBadge />
      </div>
      <WelcomeOverlay />
```
> Keep the `CommercialOverlayBadge` import (`App.tsx:25`) and the `useStore` / `useSettingsStore` imports — all
> are still used after the toolbar is gone (`useSettingsStore` by `loadSnapshot`/`vadEnabled`; `useStore` by
> `mainViewer`/`triggerInput`). Run `npm run build` (tsc) to confirm zero unused-import drift after the deletion;
> `NavButtonProps`/`NavButton`/`NavSeparator`/`TopNav` are removed together, so no dangling reference should
> remain.

### Section 4 — UPDATE: `ui/src/components/bridge/__tests__/stations.test.tsx`
AD-944 changes the AD-943 contract for three stations (empty → populated) and the factory signature, so the
AD-943 cases that assert the OLD contract are **obsolete-contract tests** and MUST be updated (not merely
appended to). Update exactly these, then add the AD-944 cases.

**4a. Every `buildBridgeStations(...)` call must pass the new `totalUnread` field** — there are three
(`stations.test.tsx:52`, `:78`, `:89`). Add `totalUnread: <n>` to each ctx object (e.g.
`buildBridgeStations({ dmChannelCount: 4, kanbanCount: 7, totalUnread: 3 })`).

**4b. Rewrite the "personnel/science/command are empty modelled placeholders (not populated)" case** (`:77`→`:88`).
Under AD-944 they ARE populated. Replace its body to assert the migrated action ids and that they now render:
```
SEARCH:
  it('personnel/science/command are empty modelled placeholders (not populated)', () => {
    const stations = buildBridgeStations({ dmChannelCount: 0, kanbanCount: 0 });
    for (const id of ['personnel', 'science', 'command'] as const) {
      const st = stations.find(s => s.id === id)!;
      expect(st.actions).toEqual([]);
      expect(st.config).toEqual([]);
      expect(st.body).toBeUndefined();
      expect(isPopulated(st)).toBe(false);
    }
  });

REPLACE:
  it('AD-944: personnel/science/command are now populated with the migrated launches', () => {
    const stations = buildBridgeStations({ dmChannelCount: 0, kanbanCount: 0, totalUnread: 0 });
    const ids = (id: string) =>
      stations.find(s => s.id === id)!.actions.map(a => a.id);
    expect(ids('personnel')).toEqual(['crew-action', 'personnel-toggle', 'behavioral-metrics-toggle']);
    expect(ids('science')).toEqual(['notebooks-toggle', 'knowledge-browser-toggle', 'spatial-explorer-toggle']);
    expect(ids('command')).toEqual(['topnav-settings']);
    for (const id of ['personnel', 'science', 'command'] as const) {
      expect(isPopulated(stations.find(s => s.id === id)!)).toBe(true);
    }
  });
```

**4c. Fix the "descriptor can HOLD a future launch" case** (`:89`→`:105`). It invokes `personnel.actions[0]`,
which is now the real `crew-action` — invoke the **pushed** action instead:
```
SEARCH:
    personnel.actions.push(action);
    // an action makes the placeholder populated, and the slot is callable
    expect(isPopulated(personnel)).toBe(true);
    personnel.actions[0].onInvoke();
    expect(fired).toBe(true);

REPLACE:
    const before = personnel.actions.length;
    personnel.actions.push(action);
    expect(isPopulated(personnel)).toBe(true);
    personnel.actions[before].onInvoke();   // invoke the pushed action, not the migrated crew launch
    expect(fired).toBe(true);
```
> Update its `buildBridgeStations(...)` call (the `:89` one) to include `totalUnread: 0` per 4a.

**4d. Extend the "returns the 6 stations … with migrated bodies/config" case** (`:51`) to assert the
communications launches (after updating its ctx per 4a):
```
SEARCH:
    const comms = stations.find(s => s.id === 'communications')!;
    expect(comms.count).toBe(4);
    expect(typeof comms.onExpand).toBe('function');
    expect(comms.body).toBeTruthy();
    expect(comms.config.map(c => c.id)).toContain('comms-admin');

REPLACE:
    const comms = stations.find(s => s.id === 'communications')!;
    expect(comms.count).toBe(4);
    expect(typeof comms.onExpand).toBe('function');
    expect(comms.body).toBeTruthy();
    expect(comms.config.map(c => c.id)).toContain('comms-admin');
    // AD-944: the two migrated communications launches; Ward Room carries totalUnread.
    expect(comms.actions.map(a => a.id)).toEqual(['ward-room-action', 'chats-toggle']);
    const wardRoom = comms.actions.find(a => a.id === 'ward-room-action')!;
    expect(wardRoom.count).toBe(3);
```
> This requires the `:52` ctx to be `{ dmChannelCount: 4, kanbanCount: 7, totalUnread: 3 }` (per 4a).

**4e. ADD an AD-944 BridgePanel render case** (real store, BF-287 — no MagicMock at the boundary; mirrors the
existing AD-943 render case). Append a new `describe`:
- Stub `global.fetch` to a resolved empty JSON (as the AD-943 case does) and seed the same empty real-store
  slices.
- Render `<BridgePanel open={true} onClose={() => {}} />`; `await screen.findByText(/SHUTDOWN/i)`.
- Assert the three newly-rendering stations appear: `getByText(/Personnel/i)`, `getByText(/Science/i)`,
  `getByText(/Command/i)`, and `container.querySelector('[data-station="personnel"]')` is truthy.
- Assert the migrated launch testIds resolve: `getByTestId('chats-toggle')`, `getByTestId('topnav-settings')`,
  `getByTestId('spatial-explorer-toggle')` (note: the rows are inside collapsed sections by default — render
  them open for the assertion by setting `defaultOpen` is NOT exposed, so instead query `container` directly:
  the rows ARE in the DOM even when the section is collapsed only if `open`; the BridgeSection renders children
  **only when expanded**. Therefore **fire a click on the station header first** to expand it, e.g.
  `fireEvent.click(screen.getByText(/Personnel/i))`, then assert `getByTestId('behavioral-metrics-toggle')`).
- Assert invoking a **sync** launch flips its store flag: `fireEvent.click(screen.getByText(/Communications/i))`
  to expand, then `fireEvent.click(screen.getByTestId('chats-toggle'))`, then
  `expect(useStore.getState().chatsOpen).toBe(true)`. (Use a sync action — `openChats` — so the flag flips
  deterministically without awaiting a fetch.)
- Assert **no emoji** in `document.body.textContent` (HXI #3).
- Reset the seeded slices + `chatsOpen` in `afterEach`.
> `fireEvent` + `screen` come from `@testing-library/react` — add `fireEvent` to the existing import. The
> `BridgeSection` renders its children only when `open` (`BridgePanel.tsx:64`), so a click-to-expand is required
> before the action rows exist in the DOM.

**Do NOT touch** `ui/src/__tests__/Ad562KnowledgeBrowserToggle.test.tsx` or
`ui/src/__tests__/SpatialExplorerToggle.test.tsx` — they render their OWN local `data-testid` stubs (NOT the
real toolbar), so they stay green and test an unrelated unit. Leave them as-is.

---

## Gates
- `cd d:\ProbOS\ui; npx vitest run` → green. **Baseline after AD-943 = 1339 passed / 1 skipped (225 files).**
  AD-944 removes no test and adds the AD-944 cases (≈ +1 to +2 net over the rewrites), so expect **≥ 1340
  passed / 1 skipped, zero regressions.** Report the exact pass count and the file count.
- `cd d:\ProbOS\ui; npm run build` → clean (`tsc -b` + `vite`). No unused-import or type drift after the toolbar
  deletion.
- `cd d:\ProbOS\ui; npx playwright test` → green. The four AD-941 specs open panels through the DEV
  `window.__store` seam (`_helpers.ts` `openChats`/`openAgentProfile`), **never** via the toolbar, so they are
  expected unaffected — run them to confirm. (Requires `vite dev` on :5173 per the AD-941 harness.)
- No backend change → **no pytest.**

## Acceptance
- The top-center `role="toolbar" aria-label="HXI panels"` block is gone from `App.tsx`; `NavButton`,
  `NavSeparator`, `NavButtonProps`, and `TopNav` are deleted (no remaining reference).
- All nine destinations open from Bridge command stations: communications (Ward Room + Chats), personnel (Crew,
  Personnel, Metrics), science (Notebooks, Records, Explorer), command (Settings). `personnel`/`science`/`command`
  now render (populated). The seven preserved testIds resolve on the new station rows; Ward Room carries the live
  `totalUnread` badge.
- `BridgePanel` now renders `st.actions` (it did not before) as stroke-SVG, no-emoji launch rows in the station
  accent. Invoking a launch calls the existing `open*` action and leaves the Bridge open/close state unchanged.
- `CommercialOverlayBadge` is re-mounted (top-left fixed band) and stays in the tree, invisible by default.
- Gates green (Vitest ≥ 1340/1, build clean, Playwright green).
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Do NOT build (scope fence)
- **Do NOT touch the bottom-right toggle cluster** — that is **AD-945**.
- **Do NOT change the omnibox / `Ask ProbOS…` pill / add a command palette** — that is **AD-946**.
- **Do NOT remove or move the Bridge open/close button or the bottom status strip** (`DecisionSurface.tsx`).
- **Do NOT change `operations` / `engineering`** — they keep their AD-943 bodies; no toolbar item maps to them.
- **Do NOT change the internals** of any destination panel (`WardRoomPanel`, `ChatsPanel`, `CrewRosterPanel`,
  `CrewPersonnelConsole`, `NotebooksPanel`, `KnowledgeBrowserPanel`, `SpatialExplorerPanel`,
  `BehavioralMetricsPanel`, `SettingsPanel`) or the `bridge/Bridge*` body components — only wire their existing
  `open*` actions.
- **Do NOT add a Bridge-close side effect** to any station action; **do NOT** flip any `defaultOpen` to `true`.
- **Do NOT modify** `Ad562KnowledgeBrowserToggle.test.tsx` / `SpatialExplorerToggle.test.tsx` (local-stub units).
- No backend / REST / FastAPI / pytest. No push. Stage explicit paths (NOT `git add -A`); deletion-audit before
  commit.

## Trackers (after gates green — match where AD-943 went)
- `docs/development/roadmap.md`: AD-944 row — SHIPPED + date + gate note; tag the epic (`#873`) / issue (`#879`).
- `PROGRESS.md`: prepend an AD-944 block (toolbar retired; the 9→station mapping; the new `StationActionRow`
  render; the badge re-home; the Vitest delta + suite count).
- `DECISIONS.md` (match where AD-943 went): AD-944 entry — the station→action placement, that BridgePanel now
  renders `actions`, the Ward-Room dual-affordance rationale, and the `CommercialOverlayBadge` re-home.

---

## Verified Against Codebase (2026-06-09)
```
PROGRESS.md:3                          "AD-943 shipped (2026-06-09 …)" → current highest AD = AD-943
BridgePanel.tsx:178-197                registry .map renders {st.body?.()} + {st.config.map(...)} ONLY — NO st.actions (AD-944 adds it)
BridgePanel.tsx:3                      import { ChevronDown, ChevronRight, Expand, Close } from './icons/Glyphs' (ChevronRight already imported)
BridgePanel.tsx:9                      import { buildBridgeStations, isPopulated, type StationId } from './bridge/stations'
BridgePanel.tsx:64                     {open && <div …>{children}</div>}  → BridgeSection renders children only when expanded
bridge/stations.tsx:66-69              buildBridgeStations(ctx: { dmChannelCount; kanbanCount }): CommandStation[]
bridge/stations.tsx:90-104             personnel/science/command placeholders — actions:[], config:[]
bridge/stations.tsx (isPopulated)      returns true when actions.length > 0 → filling actions makes them render (no edit needed)
App.tsx:34                             "// ── Top navigation ──"  (deletion-span start)
App.tsx:40 / :48 / :89 / :101          NavButtonProps / NavButton / NavSeparator / TopNav  (all defined in App.tsx, used nowhere else)
App.tsx:131-162                        <div role="toolbar" aria-label="HXI panels"> … 9 NavButton + 2 NavSeparator + <CommercialOverlayBadge/>
App.tsx:104                            totalUnread = Object.values(wardRoomUnread).reduce((s,n)=>s+n,0)
App.tsx:108                            const openCrew = useStore(s => s.openCrewManifest)  (openCrew is a LOCAL alias)
App.tsx:154 / :159                     async launches void-wrapped: onOpen={() => { void openRecords(); }} / {() => { void openSettings(); }}
App.tsx:161                            <CommercialOverlayBadge /> (mounted inside the toolbar — must be re-homed)
App.tsx:241                            <TopNav /> mount (replaced by the badge wrapper)
App.tsx:25 / :28                       import CommercialOverlayBadge … ; import { useSettingsStore } …  (both still used after removal)
useStore.ts:550/1389  516/1008  563/1483  529/1087  521/1040  543/1211  536/1204  532/1169
                                       openWardRoom(async) openCrewManifest(async) openPersonnelConsole(sync) openChats(sync)
                                       openNotebooks(async) openKnowledgeBrowser(async) openSpatialExplorer(sync) openBehavioralMetrics(async)
useSettingsStore.ts:59/134-138         openSettings: async — sets { open:true } synchronously before the await (different store)
CommercialOverlayBadge.tsx:51          data-testid="commercial-overlay-badge"; returns null unless commercial_loaded; no own positioning
IntentSurface.tsx:875                  <BridgePanel open={bridgeOpen} onClose={…}/> — props unchanged by AD-944
bridge/__tests__/stations.test.tsx:52/78/89   three buildBridgeStations(...) calls — each needs totalUnread added
bridge/__tests__/stations.test.tsx:77-88      "empty placeholders (not populated)" — OBSOLETE under AD-944, rewrite (4b)
bridge/__tests__/stations.test.tsx:99-104     personnel.actions[0].onInvoke() — index 0 is now crew-action, fix to invoke the pushed action (4c)
__tests__/Ad562KnowledgeBrowserToggle.test.tsx / SpatialExplorerToggle.test.tsx   local-stub units (NOT the real toolbar) — leave as-is
ui/e2e/_helpers.ts:258-263             openChats(page) → store.getState().openChats() — e2e opens panels via __store, NOT the toolbar → unaffected
grep "import App" / "HXI panels|toolbar|NavButton|TopNav" in ui tests → no matches → no test renders <App> or asserts the toolbar
```
