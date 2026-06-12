# AD-943 — Command-Station model + registry (Bridge as Ship's Computer, foundation)

**Target repo:** OSS (`d:\ProbOS`). **This AD = AD-943.** GitHub epic `seangalliher/ProbOS#873`; this issue `#878`.
**Mode:** Builder. Frontend only (UI). Commit local. **No push** (the Captain decides the push).
**Epic siblings (DO NOT build — awareness only):** `#879` AD-944 (migrate the 9-button top toolbar into stations,
retire it), `#880` AD-945 (fold the bottom-right 4-toggle cluster into a station config), `#881` AD-946 (Ship's
Computer command palette in the omnibox).

## Goal
Generalize the existing `BridgePanel`'s ad-hoc `BridgeSection` composition into a **reusable, typed
COMMAND-STATION model + registry**. A *station* = a menu group for one area of the ship, holding ACTION items
(open/launch) and CONFIG items (inline settings). Migrate the three existing sections — **System**,
**Communications**, **Work Board** — to render through this model. Keep the alert-driven sections
(**Attention / Active / Notifications / Recent**) and the **Shutdown** control as a SEPARATE *activity-feed* layer
(HXI Principle #9 — they are NOT stations). Establish the Ship's-Computer identity structurally (geometric, calm,
stroke-SVG glyphs only, **NO emoji** per HXI #3; reuse existing color tokens). A deeper visual pass is the forward
marker **AD-943a**.

This AD is **additive — NO nav removal.** The top toolbar (AD-944), the bottom-right cluster (AD-945) and the
omnibox (AD-946) are untouched. AD-943 only MODELS the 6-station taxonomy and migrates the 3 existing sections;
the 3 empty stations are placeholders the later ADs fill.

## Why a model (Captain-approved epic intent)
The Bridge is the single "Ship's Computer" surface — a modern, FAMILIAR control surface, deliberately distinct
from the bioluminescent agent mesh (the Ship's Computer is NOT an agent; AD-398 "a microwave with a name tag
isn't a person"). Today the Bridge sections are hand-written one-offs; AD-944/945/946 each need a typed slot to
drop a launch/config item into. AD-943 builds that slot once, correctly, so the later ADs are pure data edits.

Reference: `docs/design/hxi-glass-bridge.md` ("the Bridge is the crew's report", Zone-4 "not an app launcher");
the 11 HXI Design Principles in `.github/copilot-instructions.md`.

---

## Verified current shape (grep evidence in the footer)
- `ui/src/components/BridgePanel.tsx:13` — `BridgeSection({ title, count, defaultOpen, accentColor?, onExpand?, children })`,
  a collapsible shell (chevron + uppercase-mono accent title + optional `Expand` glyph on `onExpand`).
- The scroll area (`BridgePanel.tsx` `167`→`245`; Shutdown footer at `:248`) renders, in order: **System**
  (`accent #70a0d0`, `count 0`,
  `onExpand → mainViewer:'system'`, body `<BridgeSystem/>`), **Communications** (`accent #b080d0`,
  `count dmChannels.length`, `onExpand → wardRoomOpen:true, wardRoomView:'channels'`, body = a `THREADS` label +
  `<BridgeThreads/>`, plus inline config `<BridgeCommunications/>`), **Attention/Active/Notifications** (alert
  feed), **Work Board** (`accent #d0a030`, `count kanbanTasks.length`, `onExpand → mainViewer:'work'`, body
  `<BridgeKanban/>`), **Recent**, empty-state, then a fixed **Shutdown** footer (`<BridgeShutdown/>`).
- `onExpand` targets are real store fields: `mainViewer: 'canvas'|'kanban'|'system'|'work'|'bills'`
  (`useStore.ts:296`; `App.tsx:221` routes `'work'→<WorkBoard/>`, else `<FullSystem/>`), `wardRoomOpen`
  (`:368`), `wardRoomView: 'channels'|'dms'|'dm-detail'` (`:374`). **Preserve these exactly.**
- Bodies live in `ui/src/components/bridge/`: `BridgeSystem.tsx` exports `BridgeSystem` (service-status list),
  `BridgeThreads`, `BridgeShutdown`; `BridgeCommunications.tsx` exports `BridgeCommunications` (DM-rank +
  recreation settings + DM search/list); `BridgeKanban.tsx` exports `BridgeKanban`; `BridgeCards.tsx` /
  `BridgeNotifications.tsx` export the card components. **Do NOT change any of these internals — reuse as-is.**
- `BridgePanel` is mounted by `IntentSurface.tsx:875` as `<BridgePanel open={bridgeOpen} onClose={…}/>`
  (`bridgeOpen` flag `useStore.ts:295/807`). Unchanged.
- Stroke-SVG glyph set: `ui/src/components/icons/Glyphs.tsx` (`ChevronDown/Right/Up`, `Close`, `Expand`,
  `Diamond`, `DiamondOpen`, …). Reuse these; NO emoji.

## Future actions the descriptor must be able to HOLD (AD-944 — DO NOT wire here)
Confirm-only; AD-943 leaves `actions: []` on every station. Real store-action names (verified):
`openWardRoom` (`useStore.ts:550/1389`), `openChats` (`:529/1087`), `openCrewManifest` (`:516/1008` — **note:
`openCrew` is only a LOCAL alias in `App.tsx:108`; the store action is `openCrewManifest`**),
`openPersonnelConsole` (`:563/1483`), `openBehavioralMetrics` (`:532/1169`), `openNotebooks` (`:521/1040`),
`openKnowledgeBrowser` (`:543/1211`), `openSpatialExplorer` (`:536/1204`), `openSettings`
(`useSettingsStore.ts:59/134`). Suggested (non-binding) placement for AD-944: Communications ← openWardRoom,
openChats; Personnel ← openCrewManifest, openPersonnelConsole, openBehavioralMetrics; Science ← openNotebooks,
openKnowledgeBrowser, openSpatialExplorer; Command ← openSettings. The 6-station taxonomy holds all 9.

---

## The station descriptor (the contract)
| field | type | AD-943 use |
|---|---|---|
| `id` | `StationId` union | one of the 6 stations |
| `title` | `string` | header label (uppercased by the shell) |
| `accent` | `string` (hex token) | reuses the existing per-section color |
| `defaultOpen` | `boolean` | collapsed by default (`false`) |
| `count?` | `number` | live header count (dmChannels / kanban) |
| `onExpand?` | `() => void` | the `Expand` launch (preserves existing setState) |
| `body?` | `() => ReactNode` | inline body (migrated System/Comms/Work bodies) |
| `actions` | `StationAction[]` | discrete launches — **empty until AD-944** |
| `config` | `StationConfig[]` | inline config surfaces (Comms DM-rank today) |

`StationAction = { id; label; onInvoke: () => void; count? }`.
`StationConfig = { id; label; render: () => ReactNode }`.

### Station mapping (the decision)
| Existing section | → Station | accent (unchanged) | rationale |
|---|---|---|---|
| **Communications** | `communications` | `#b080d0` | direct — already an action (Ward Room expand) + config (DM rank) |
| **Work Board** | `operations` | `#d0a030` | the mission/task pipeline = running the ship's work |
| **System** (services) | `engineering` | `#70a0d0` | ship subsystems / "is the machinery online" |
| — | `personnel` | `#50b0a0` | placeholder (crew, roster, behavioral metrics) |
| — | `science` | `#5090d0` | placeholder (records, notebooks, spatial explorer) |
| — | `command` | `#f0b060` | placeholder (settings, high-level command) |

The visible headers of the two migrated sections are **renamed to the station name**: `System → Engineering`,
`Work Board → Operations` (`Communications` unchanged). Accents + `onExpand` targets are preserved. **Verified
safe:** the only tests asserting `"SYSTEM"`/`"WORK"` strings are
[ComponentRendering.test.tsx](ui/src/__tests__/ComponentRendering.test.tsx#L117) which tests the **`ViewSwitcher`**,
NOT `BridgePanel` (see footer).

---

## Files

### Section 0 — NEW: `ui/src/components/bridge/stations.tsx`
The typed model, the canonical taxonomy metadata, and the build factory. `.tsx` (the `body`/`config.render`
closures return JSX). Bodies are imported and reused verbatim — no behavior change.

```tsx
/* AD-943: Command-Station model + registry — the Bridge's Ship's-Computer
 * command layer. A station = a menu group for one area of the ship, holding
 * launch ACTIONS and inline CONFIG. The 3 existing Bridge sections are migrated
 * here; personnel/science/command are modelled placeholders the AD-944/945/946
 * wave fills. NOT an agent surface (AD-398). Deep visual pass = AD-943a. */
import type { ReactNode } from 'react';
import { useStore } from '../../store/useStore';
import { BridgeSystem, BridgeThreads } from './BridgeSystem';
import { BridgeKanban } from './BridgeKanban';
import { BridgeCommunications } from './BridgeCommunications';

export type StationId =
  | 'communications' | 'personnel' | 'science'
  | 'operations' | 'engineering' | 'command';

/** A discrete "open / launch" item a station offers. AD-944 fills these with
 *  store actions (openWardRoom, openCrewManifest, …). Empty in AD-943. */
export interface StationAction {
  id: string;
  label: string;
  onInvoke: () => void;
  count?: number;
}

/** An inline configuration surface embedded in a station (e.g. the
 *  Communications DM-rank settings). AD-945 folds the bottom-right toggles in. */
export interface StationConfig {
  id: string;
  label: string;
  render: () => ReactNode;
}

/** A command station = a menu group for one area of the ship. */
export interface CommandStation {
  id: StationId;
  title: string;
  accent: string;            // reuses an existing per-section color token
  defaultOpen: boolean;
  count?: number;            // live header count (e.g. dmChannels.length)
  onExpand?: () => void;     // primary launch (the section Expand affordance)
  body?: () => ReactNode;    // inline body (migrated System/Comms/Work bodies)
  actions: StationAction[];  // discrete launches (empty until AD-944)
  config: StationConfig[];   // inline config surfaces
}

/** Canonical 6-station taxonomy — pure, presentation-free metadata. All accents
 *  reuse existing tokens (no new colors). */
export const STATION_META: Record<StationId, { title: string; accent: string }> = {
  communications: { title: 'Communications', accent: '#b080d0' },
  personnel:      { title: 'Personnel',      accent: '#50b0a0' },
  science:        { title: 'Science',        accent: '#5090d0' },
  operations:     { title: 'Operations',     accent: '#d0a030' },
  engineering:    { title: 'Engineering',    accent: '#70a0d0' },
  command:        { title: 'Command',        accent: '#f0b060' },
};

/** The Bridge render order for the stations layer. */
export const STATION_ORDER: StationId[] = [
  'communications', 'personnel', 'science', 'operations', 'engineering', 'command',
];

/** Build the typed station list. The 3 existing Bridge sections are migrated
 *  here (Communications, Work Board→operations, System→engineering);
 *  personnel/science/command are MODELLED placeholders (empty actions/config,
 *  no body) that AD-944/945/946 fill. */
export function buildBridgeStations(ctx: {
  dmChannelCount: number;
  kanbanCount: number;
}): CommandStation[] {
  const m = STATION_META;
  return [
    {
      id: 'communications',
      title: m.communications.title,
      accent: m.communications.accent,
      defaultOpen: false,
      count: ctx.dmChannelCount,
      onExpand: () => useStore.setState({ wardRoomOpen: true, wardRoomView: 'channels' }),
      body: () => (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 9, color: '#666', marginBottom: 4, fontWeight: 600 }}>THREADS</div>
          <BridgeThreads />
        </div>
      ),
      actions: [],
      config: [
        { id: 'comms-admin', label: 'Communications', render: () => <BridgeCommunications /> },
      ],
    },
    {
      id: 'personnel',
      title: m.personnel.title, accent: m.personnel.accent,
      defaultOpen: false, actions: [], config: [],
    },
    {
      id: 'science',
      title: m.science.title, accent: m.science.accent,
      defaultOpen: false, actions: [], config: [],
    },
    {
      id: 'operations',
      title: m.operations.title,
      accent: m.operations.accent,
      defaultOpen: false,
      count: ctx.kanbanCount,
      onExpand: () => useStore.setState({ mainViewer: 'work' }),
      body: () => <BridgeKanban />,
      actions: [],
      config: [],
    },
    {
      id: 'engineering',
      title: m.engineering.title,
      accent: m.engineering.accent,
      defaultOpen: false,
      count: 0,
      onExpand: () => useStore.setState({ mainViewer: 'system' }),
      body: () => <BridgeSystem />,
      actions: [],
      config: [],
    },
    {
      id: 'command',
      title: m.command.title, accent: m.command.accent,
      defaultOpen: false, actions: [], config: [],
    },
  ];
}

/** A station renders in AD-943 iff it has a body, an action, or a config item.
 *  Placeholders are modelled but NOT shown until later ADs fill them. */
export function isPopulated(st: CommandStation): boolean {
  return !!st.body || st.actions.length > 0 || st.config.length > 0;
}
```

### Section 1 — MODIFY: `ui/src/components/BridgePanel.tsx`

**1a. Import the registry + the StationId type.** Add after the existing `BridgeCommunications` import:
```
SEARCH:
import { BridgeSystem, BridgeThreads, BridgeShutdown } from './bridge/BridgeSystem';
import { BridgeCommunications } from './bridge/BridgeCommunications';

REPLACE:
import { BridgeSystem, BridgeThreads, BridgeShutdown } from './bridge/BridgeSystem';
import { BridgeCommunications } from './bridge/BridgeCommunications';
import { buildBridgeStations, isPopulated, type StationId } from './bridge/stations';
```
After this, `BridgeSystem`, `BridgeThreads`, `BridgeCommunications`, `BridgeKanban` are still imported but now
referenced only via the registry — they remain imported because `stations.tsx` is what uses them; **remove the
now-unused direct imports** in `BridgePanel.tsx` that the registry replaces (`BridgeSystem`, `BridgeThreads`,
`BridgeCommunications`, `BridgeKanban` — but KEEP `BridgeShutdown`, `TaskCard`, `NotificationCard`, the `Glyphs`).
Run `npm run build` (tsc) to catch any unused-import drift and fix accordingly. Do not leave dead imports.

**1b. Add a station-identity hook to `BridgeSection`.** Extend the shell so true stations carry a `data-station`
attribute and an accent left-edge (the functional distinction: command-station layer vs activity-feed layer).
Additive optional prop; activity-feed sections omit it.
```
SEARCH:
function BridgeSection({
  title, count, defaultOpen, accentColor, onExpand, children,
}: {
  title: string; count: number; defaultOpen: boolean;
  accentColor?: string; onExpand?: () => void;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const color = accentColor || '#888';

  return (
    <div>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          padding: '8px 12px',
          cursor: 'pointer',
          userSelect: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          borderBottom: '1px solid rgba(255,255,255,0.06)',
        }}
      >

REPLACE:
function BridgeSection({
  title, count, defaultOpen, accentColor, onExpand, stationId, children,
}: {
  title: string; count: number; defaultOpen: boolean;
  accentColor?: string; onExpand?: () => void;
  stationId?: StationId;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const color = accentColor || '#888';

  return (
    <div>
      <div
        data-station={stationId}
        onClick={() => setOpen(o => !o)}
        style={{
          padding: '8px 12px',
          cursor: 'pointer',
          userSelect: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          // AD-943: the command-station layer carries its accent edge; the
          // activity-feed sections (no stationId) do not — a glanceable
          // distinction (HXI #6), reusing the accent token (no new color).
          borderLeft: stationId ? `2px solid ${color}` : undefined,
        }}
      >
```

**1c. Replace the scroll-area children** with the stations block (driven by the registry) followed by the
activity-feed layer. The current children run System → Communications → Attention → Active → Notifications →
Work Board → Recent → empty-state. The new order groups the populated stations FIRST (Communications,
Operations, Engineering — Work Board moves up out of the activity feed), then the activity-feed layer
(Attention / Active / Notifications / Recent), then the empty-state. Replace the inner JSX of the
`{/* Scrollable content */}` div:

```
SEARCH:
      {/* Scrollable content */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden' }}>
        {/* SYSTEM — services only */}
        <BridgeSection title="System" count={0} defaultOpen={false} accentColor="#70a0d0"
          onExpand={() => useStore.setState({ mainViewer: 'system' })}>
          <BridgeSystem />
        </BridgeSection>

        {/* COMMUNICATIONS — threads + DMs */}
        <BridgeSection title="Communications" count={dmChannels.length} defaultOpen={false} accentColor="#b080d0"
          onExpand={() => useStore.setState({ wardRoomOpen: true, wardRoomView: 'channels' })}>
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 9, color: '#666', marginBottom: 4, fontWeight: 600 }}>THREADS</div>
            <BridgeThreads />
          </div>
          <BridgeCommunications />
        </BridgeSection>

        {/* ATTENTION */}
        {attentionCount > 0 && (
          <BridgeSection title="Attention" count={attentionCount} defaultOpen={true} accentColor="#f0b060">
            {attentionTasks.map(t => <TaskCard key={t.id} task={t} />)}
            {attentionNotifs.map(n => <NotificationCard key={n.id} notification={n} />)}
          </BridgeSection>
        )}

        {/* ACTIVE */}
        {activeTasks.length > 0 && (
          <BridgeSection title="Active" count={activeTasks.length} defaultOpen={true} accentColor="#50b0a0">
            {activeTasks.map(t => <TaskCard key={t.id} task={t} />)}
          </BridgeSection>
        )}

        {/* NOTIFICATIONS */}
        {infoNotifs.length > 0 && (
          <BridgeSection
            title="Notifications"
            count={infoNotifs.length}
            defaultOpen={unreadNotifs > 0}
            accentColor="#5090d0"
          >
            {infoNotifs.map(n => <NotificationCard key={n.id} notification={n} />)}
          </BridgeSection>
        )}

        {/* WORK BOARD — always visible */}
        <BridgeSection
          title="Work Board"
          count={kanbanTasks.length}
          defaultOpen={false}
          accentColor="#d0a030"
          onExpand={() => useStore.setState({ mainViewer: 'work' })}
        >
          <BridgeKanban />
        </BridgeSection>

        {/* RECENT */}
        {recentTasks.length > 0 && (
          <BridgeSection title="Recent" count={recentTasks.length} defaultOpen={false} accentColor="#666">
            {recentTasks.map(t => <TaskCard key={t.id} task={t} />)}
          </BridgeSection>
        )}

        {/* Empty state */}
        {attentionCount === 0 && activeTasks.length === 0 && infoNotifs.length === 0 &&
         kanbanTasks.length === 0 && recentTasks.length === 0 && (
          <div style={{
            fontSize: 10, color: '#555', fontStyle: 'italic',
            textAlign: 'center', padding: '32px 0',
          }}>
            No activity
          </div>
        )}
      </div>

REPLACE:
      {/* Scrollable content */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden' }}>
        {/* ── COMMAND STATIONS — the Ship's-Computer command layer (AD-943).
            Driven by the typed registry; the 3 existing sections migrate here.
            personnel/science/command are modelled placeholders (no body yet),
            hidden by isPopulated until AD-944/945/946 fill them. ── */}
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

        {/* ── ACTIVITY FEED — alert-driven, NOT stations (HXI #9). These rise
            and recede with system state; they carry no stationId. ── */}
        {/* ATTENTION */}
        {attentionCount > 0 && (
          <BridgeSection title="Attention" count={attentionCount} defaultOpen={true} accentColor="#f0b060">
            {attentionTasks.map(t => <TaskCard key={t.id} task={t} />)}
            {attentionNotifs.map(n => <NotificationCard key={n.id} notification={n} />)}
          </BridgeSection>
        )}

        {/* ACTIVE */}
        {activeTasks.length > 0 && (
          <BridgeSection title="Active" count={activeTasks.length} defaultOpen={true} accentColor="#50b0a0">
            {activeTasks.map(t => <TaskCard key={t.id} task={t} />)}
          </BridgeSection>
        )}

        {/* NOTIFICATIONS */}
        {infoNotifs.length > 0 && (
          <BridgeSection
            title="Notifications"
            count={infoNotifs.length}
            defaultOpen={unreadNotifs > 0}
            accentColor="#5090d0"
          >
            {infoNotifs.map(n => <NotificationCard key={n.id} notification={n} />)}
          </BridgeSection>
        )}

        {/* RECENT */}
        {recentTasks.length > 0 && (
          <BridgeSection title="Recent" count={recentTasks.length} defaultOpen={false} accentColor="#666">
            {recentTasks.map(t => <TaskCard key={t.id} task={t} />)}
          </BridgeSection>
        )}

        {/* Empty state — the activity feed is empty (stations always render). */}
        {attentionCount === 0 && activeTasks.length === 0 && infoNotifs.length === 0 &&
         recentTasks.length === 0 && (
          <div style={{
            fontSize: 10, color: '#555', fontStyle: 'italic',
            textAlign: 'center', padding: '32px 0',
          }}>
            No activity
          </div>
        )}
      </div>
```
> Note: the empty-state condition drops `kanbanTasks.length === 0` (the Work Board is now a station that always
> renders, so it is no longer part of the "No activity" activity-feed test). `kanbanTasks` is still read for the
> Operations station count. The `BridgeShutdown` footer below the scroll area is **unchanged**.

### Section 2 — NEW: `ui/src/components/bridge/__tests__/stations.test.tsx`
Vitest. The model unit tests are pure (no render); the panel test seeds the **REAL** store via
`useStore.setState` (BF-287 — no MagicMock/over-mock at the boundary), mirroring
[ChatsPanel.drag.test.tsx](ui/src/components/chats/__tests__/ChatsPanel.drag.test.tsx). Stub `global.fetch`
to a resolved empty JSON so the bodies' effect-driven fetches honest-degrade in jsdom.

Required cases:
1. `STATION_ORDER` equals `['communications','personnel','science','operations','engineering','command']`; every
   `STATION_META[id]` has a non-empty `title`, an accent matching `/^#[0-9a-fA-F]{6}$/`, and **no emoji** in the
   title (`/\p{Extended_Pictographic}/u` — HXI #3).
2. `buildBridgeStations({dmChannelCount:4, kanbanCount:7})`: `.map(s=>s.id)` equals `STATION_ORDER`;
   `communications` has `count===4`, a function `onExpand`, a truthy `body`, and a `config` containing
   `comms-admin`; `operations` has `count===7`, `onExpand`, `body`; `engineering` has `onExpand`, `body`;
   `personnel`/`science`/`command` have `actions===[]`, `config===[]`, `body===undefined`, and
   `isPopulated(...)===false`; every station's `actions` and `config` are arrays.
3. The descriptor can HOLD a future launch (AD-944 shape): push a `StationAction` onto a placeholder's `actions`,
   invoke `onInvoke`, assert the side effect fired (proves the slot is real and callable).
4. Render `<BridgePanel open={true} onClose={()=>{}} />` with a seeded REAL store (one info `notifications`
   entry for the activity feed; `wardRoomDmChannels: []`, `missionControlTasks: []`, `agentTasks: []`). Assert:
   the three migrated station headers render (`/Communications/i`, `/Operations/i`, `/Engineering/i`); the
   identity hooks exist (`[data-station="communications"]`, `[data-station="engineering"]`); the activity feed
   still renders (`/Notifications/i` from the seeded notification); the **Shutdown** footer survives
   (`/SHUTDOWN/i`); and there is **no emoji** anywhere in `document.body.textContent` (HXI #3). Reset the seeded
   slices in `afterEach` + `cleanup()`.

---

## Gates
- `cd d:\ProbOS\ui; npx vitest run` → green. **Full UI suite ≥ 1333 passed / 1 skipped** (the AD-942 baseline;
  the new `stations.test.tsx` adds tests, zero regressions). Report the pass count.
- `cd d:\ProbOS\ui; npm run build` → clean (`tsc -b` + `vite`). No unused-import or type drift.
- No backend change → **no pytest**.

## Acceptance
- A typed `CommandStation` model + a 6-station registry exist in `ui/src/components/bridge/stations.tsx`; the
  descriptor can hold `actions[]` (launches) and `config[]` (inline settings) for the AD-944/945 wave.
- `BridgePanel` renders the Communications / Operations / Engineering stations **through the registry** (bodies
  byte-equivalent to today: services list, THREADS + comms admin, kanban), with the alert-driven
  Attention/Active/Notifications/Recent kept as a separate activity-feed layer and the Shutdown footer
  unchanged. `System→Engineering` and `Work Board→Operations` header renames applied; accents + `onExpand`
  targets preserved.
- Ship's-Computer identity: stroke-SVG glyphs only, NO emoji, accent tokens reused, a `data-station` hook +
  accent edge distinguishing the command layer. Deep visual pass deferred to **AD-943a**.
- Gates green (Vitest ≥ 1333/1, build clean).
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Do NOT build (scope fence)
- **Do NOT remove or migrate the 9-button top toolbar** (it lives in `App.tsx` ~`108`→`123`) — that is **AD-944**.
  Leave it exactly as-is.
- **Do NOT move or fold the bottom-right toggle cluster** into a station config — that is **AD-945**.
- **Do NOT change the omnibox / `Ask ProbOS…` pill / add a command palette** — that is **AD-946**.
- **Do NOT wire any `open*` store action** into a station yet — `actions: []` everywhere. Model only.
- **Do NOT change** the internals of `BridgeSystem.tsx`, `BridgeCommunications.tsx`, `BridgeKanban.tsx`,
  `BridgeCards.tsx`, `BridgeNotifications.tsx` — reuse them as-is.
- **Do NOT touch** `GlassLayer.tsx`, the mesh status strip (`DecisionSurface.tsx`), the mesh canvas
  (`CognitiveCanvas.tsx`), or `ViewSwitcher.tsx`.
- No backend / REST / FastAPI / pytest. No push. Stage explicit paths (NOT `git add -A`); deletion-audit before
  commit.

## Trackers (after gates green)
- `docs/development/roadmap.md`: AD-943 row — SHIPPED + date + gate note; tag the epic (`#873`) / issue (`#878`).
- `PROGRESS.md`: prepend an AD-943 block (the model + registry, the 3-section migration, the activity-feed split,
  the identity beat, the forward marker AD-943a, the Vitest delta + suite count).
- `DECISIONS.md` (match where AD-942 went): AD-943 entry — the `CommandStation` descriptor, the 6-station
  taxonomy + mapping (System→engineering, Work Board→operations, Communications), why the activity feed is NOT a
  station (HXI #9), and the `data-station` identity hook.

---

## Verified Against Codebase (2026-06-09)
```
PROGRESS.md:2                       AD-942 shipped … (current highest AD = AD-942)
BridgePanel.tsx:13                  function BridgeSection({ title, count, defaultOpen, accentColor, onExpand, children })
BridgePanel.tsx:167                 {/* Scrollable content */} (the div whose children are replaced in 1c)
BridgePanel.tsx:170                 <BridgeSection title="System" … accentColor="#70a0d0" onExpand={…mainViewer:'system'}> <BridgeSystem/>
BridgePanel.tsx:176                 <BridgeSection title="Communications" count={dmChannels.length} accentColor="#b080d0" onExpand={…wardRoomOpen:true,wardRoomView:'channels'}> THREADS + <BridgeThreads/> + <BridgeCommunications/>
BridgePanel.tsx:214                 <BridgeSection title="Work Board" count={kanbanTasks.length} accentColor="#d0a030" onExpand={…mainViewer:'work'}> <BridgeKanban/>
BridgePanel.tsx:9 / :248            import { …, BridgeShutdown } from './bridge/BridgeSystem'  /  <BridgeShutdown/> footer (outside scroll, unchanged)
bridge/BridgeSystem.tsx             export function BridgeSystem / BridgeThreads / BridgeShutdown
bridge/BridgeCommunications.tsx     export function BridgeCommunications (DM-rank + recreation + DM search/list)
bridge/BridgeKanban.tsx             export function BridgeKanban
bridge/BridgeCards.tsx              export DEPT_COLORS / STATUS_COLORS / TaskCard …
bridge/BridgeNotifications.tsx      export NotificationCard / TYPE_COLORS …
IntentSurface.tsx:875               <BridgePanel open={bridgeOpen} onClose={…}/>   (bridgeOpen: useStore.ts:295/807)
useStore.ts:296                     mainViewer: 'canvas'|'kanban'|'system'|'work'|'bills'
useStore.ts:368 / :374              wardRoomOpen: boolean ; wardRoomView: 'channels'|'dms'|'dm-detail'
App.tsx:221                         mainViewer==='work' ? <WorkBoard/> : … <FullSystem/>
App.tsx:108-123                     the 9-button toolbar (openCrew=openCrewManifest alias, openRecords, openExplorer) — AD-944 target
useStore.ts:550/529/516/563/532/521/543/536   openWardRoom/openChats/openCrewManifest/openPersonnelConsole/openBehavioralMetrics/openNotebooks/openKnowledgeBrowser/openSpatialExplorer
useSettingsStore.ts:59/134          openSettings
icons/Glyphs.tsx                    ChevronDown/ChevronRight/Expand/Close/Diamond/DiamondOpen … (stroke-SVG, no emoji)
ComponentRendering.test.tsx:117-130 getByText('SYSTEM')/('WORK') asserts the ViewSwitcher (NOT BridgePanel) → rename is baseline-safe
chats/__tests__/ChatsPanel.drag.test.tsx   BF-287 real-store test convention (useStore.setState/getState + @testing-library/react)
GlassLayer.tsx / DecisionSurface.tsx / CognitiveCanvas (App.tsx:221)   do-NOT-touch surfaces
```
