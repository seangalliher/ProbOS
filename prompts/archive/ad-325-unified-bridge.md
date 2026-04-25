# AD-325: Unified Bridge — Single Panel HXI Redesign

## Overview

Replace the three separate header buttons (NOTIF, ACTIVITY, MISSION CTRL) with a
single **BRIDGE** button that opens a unified command panel. The Bridge is the
Captain's primary interface to crew activity — notifications, tasks, and mission
overview are all visible in a single, contextual panel.

Design principles: **fluid, dynamic, contextual, immersive, infinite, adaptive.**

The HXI has two zones:

1. **Bridge Panel** (right sidebar) — the command console. Always-available
   status: attention items, active tasks, notifications, kanban summary, recent.
2. **Main Viewer** (center) — the adaptive focus surface. Defaults to the 3D
   cognitive canvas, but can switch to other views: full kanban, chat thread,
   or future content (video, docs, email). The Captain never loses focus — what
   they need is always front and center.

The 3D canvas is the default main viewer. It is never fully hidden — when the
Bridge panel is open, the canvas remains visible behind/beside it. Other main
viewer modes (kanban, etc.) replace the canvas area when activated.

## Architecture

### Single Panel, Multiple Sections

The Bridge is a single right-side panel (like the current ActivityDrawer) that
contains **all three data streams** in a unified, scrollable layout:

```
┌──────────────────────────────────────────────────┐
│  BRIDGE                              [×] close   │
│──────────────────────────────────────────────────│
│                                                   │
│  ⚠ ATTENTION (2)              ← amber section    │
│  ┌─ Notification: action_required ──────────────┐│
│  │ Security scan found 3 issues      ⚠ 2m ago  ││
│  └──────────────────────────────────────────────┘│
│  ┌─ Task: requires_action ──────────────────────┐│
│  │ Build AD-325: Review needed   Step 4/5  5m   ││
│  │ [Approve] [Reject]                           ││
│  └──────────────────────────────────────────────┘│
│                                                   │
│  ● ACTIVE (3)                 ← working section   │
│  ┌─ Task ───────────────────────────────────────┐│
│  │ Building AD-324              Step 2/5  1m    ││
│  │ ████████░░░░░░░ 40%                          ││
│  └──────────────────────────────────────────────┘│
│  ┌─ Task ───────────────────────────────────────┐│
│  │ Diagnosing runtime anomaly   Step 1/3  30s   ││
│  └──────────────────────────────────────────────┘│
│                                                   │
│  ○ NOTIFICATIONS (5)          ← info section      │
│  ┌──────────────────────────────────────────────┐│
│  │ Build completed successfully    eng · 10m    ││
│  │ Dream cycle report available    med · 15m    ││
│  │ ...                                          ││
│  └──────────────────────────────────────────────┘│
│                                                   │
│  □ KANBAN                     ← expandable        │
│  ┌──────────────────────────────────────────────┐│
│  │ QUEUED(2) │ WORKING(3) │ REVIEW(1) │ DONE(8) ││
│  │  ...      │   ...      │   ...     │   ...   ││
│  └──────────────────────────────────────────────┘│
│                                                   │
│  ◇ RECENT (10)                ← collapsed default │
│  ┌──────────────────────────────────────────────┐│
│  │ ✓ Build AD-323 done          eng · 1h ago    ││
│  │ ✗ Diagnostic failed           med · 2h ago   ││
│  └──────────────────────────────────────────────┘│
│                                                   │
└──────────────────────────────────────────────────┘
```

### Section Priority (Top to Bottom)

1. **ATTENTION** — Items needing Captain action. Merges `requires_action` tasks
   AND `action_required` notifications. Always expanded when items exist. Amber
   styling. This section is the reason the Bridge exists — surface what matters.

2. **ACTIVE** — Currently working tasks (from `agentTasks` where
   `status === 'working'`). Always expanded. Shows progress bars, step labels.

3. **NOTIFICATIONS** — Info/error notifications not requiring action (filtered
   from `notifications` where `notification_type !== 'action_required'` or
   already acknowledged `action_required`). Collapsible with unread count.

4. **KANBAN** — Compact inline kanban (from `missionControlTasks`). Shows column
   counts with expand-to-see-cards. Collapsible, default collapsed.

5. **RECENT** — Completed/failed tasks. Collapsible, default collapsed. Same as
   current ActivityDrawer "Recent" section.

### Key Design Rules

- **Attention section auto-promotes:** If a task becomes `requires_action` or an
  `action_required` notification arrives, the item appears at the top in
  ATTENTION — not buried in its normal section.
- **Sections with 0 items are hidden entirely** — no empty section headers.
- **Click-to-expand on each card** for full details (same expand pattern as
  current ActivityDrawer TaskCard).
- **Notifications auto-acknowledged on view** — when the Bridge is open, info
  notifications are marked as read after 3 seconds of visibility (use
  IntersectionObserver or simple timeout). Action-required notifications require
  explicit interaction.

### Main Viewer — Adaptive Focus Surface

The center area of the HXI (where the 3D canvas lives) becomes a switchable
focus surface. This is the "main screen on the bridge" — it shows whatever the
Captain is focused on.

**Viewer modes** (stored in Zustand as `mainViewer`):

| Mode | Shows | When |
|------|-------|------|
| `'canvas'` | 3D cognitive canvas (default) | Default view, always available |
| `'kanban'` | Full-width kanban board | Captain clicks KANBAN section header in Bridge panel |

Future modes (not implemented in this AD, but the architecture supports them):
`'chat'` (elevated conversation thread), `'video'` (embedded media),
`'docs'` (document viewer), `'email'` (compose/read). These will be added as
the HXI evolves.

**Viewer switching:**
- The Bridge panel's KANBAN section header gets a small "expand" icon (⬔ or
  similar). Clicking it sets `mainViewer: 'kanban'` — the full kanban replaces
  the 3D canvas in the center area.
- When in kanban mode, the KANBAN section in the Bridge panel shows a "collapse"
  icon or is hidden (since the kanban is now full-screen). The Bridge panel
  itself remains visible on the right.
- A small view switcher appears in the **top-left corner** when the main viewer
  is not `'canvas'`:
  ```
  [◉ Canvas] [☰ Kanban]
  ```
  Clicking "Canvas" returns to `mainViewer: 'canvas'`. This is a minimal
  breadcrumb — not a permanent toolbar. It only appears when non-default view
  is active.

**Implementation:**

In `CognitiveCanvas.tsx` (or its parent), conditionally render based on
`mainViewer`:
```typescript
const mainViewer = useStore(s => s.mainViewer);

// In the render:
{mainViewer === 'canvas' && <Canvas>...</Canvas>}
{mainViewer === 'kanban' && <FullKanban />}
```

The `FullKanban` component is a full-width version of the kanban (not the
compact Bridge sidebar version). It reuses the same `missionControlTasks`
data and column logic from `bridge/BridgeKanban.tsx`, but renders at full
width with larger cards showing full detail (approve/reject buttons, error
text, step progress). This is essentially the current `MissionControl.tsx`
layout, preserved as `bridge/FullKanban.tsx`.

**View switcher component** (`ViewSwitcher`):
- Only rendered when `mainViewer !== 'canvas'`.
- Position: `fixed`, `top: 12`, `left: 12`, `zIndex: 25`.
- Tab-style buttons: active tab highlighted, inactive dimmed.
- Clicking sets `mainViewer` in the store.
- For this AD, only two tabs: Canvas and Kanban.

### Bridge + Main Viewer Interaction

The Bridge panel and the main viewer are independent but connected:
- Bridge panel is a **right sidebar** (380px). Main viewer fills the
  **remaining space** to the left.
- When Bridge is closed, main viewer is full-width.
- When Bridge is open, the main viewer area narrows but the canvas/kanban
  adapts (no fixed-width assumptions — the 3D canvas already handles resize
  via R3F, and the kanban grid can use fluid columns).
- The conversation input remains at the bottom center, independent of both.

## Changes

### 1. New `BridgePanel.tsx` component

Create `ui/src/components/BridgePanel.tsx` — the unified panel replacing
ActivityDrawer, NotificationDropdown, and MissionControl.

**Props:** `{ open: boolean; onClose: () => void }`

**Positioning & styling:**
- Same approach as current ActivityDrawer: `position: fixed`, `top: 0`,
  `right: 0`, `bottom: 0`.
- Width: `380px` (slightly wider than current 320px to accommodate kanban).
- Slide animation: `transform: open ? 'translateX(0)' : 'translateX(100%)'`,
  `transition: 'transform 0.25s ease-out'`.
- Glass morphism: `background: 'rgba(10, 10, 18, 0.92)'`,
  `backdropFilter: 'blur(16px)'`.
- `zIndex: 20`.
- `pointerEvents: open ? 'auto' : 'none'`.
- Always in DOM (like current ActivityDrawer), not conditionally rendered.

**Header:**
- Label: `BRIDGE` — amber `#f0b060`, uppercase, `letterSpacing: 2`, `fontSize: 11`.
- Right side: "Mark all read" (only when unread notifications > 0) + close ×.
- Bottom border: `1px solid rgba(255,255,255,0.08)`.

**Data sources (all from Zustand store):**
```typescript
const agentTasks = useStore(s => s.agentTasks);
const notifications = useStore(s => s.notifications);
const missionControlTasks = useStore(s => s.missionControlTasks);
```

**Section rendering:**

Each section uses a shared `BridgeSection` sub-component:
```typescript
function BridgeSection({
  title: string,
  count: number,
  defaultOpen: boolean,
  accentColor?: string,  // defaults to '#888'
  children: React.ReactNode
})
```
- Collapsible header with chevron indicator (▸ collapsed, ▾ expanded).
- Section header styled: `fontSize: 10`, `fontWeight: 700`,
  `letterSpacing: 1.5`, `textTransform: 'uppercase'`,
  `color: accentColor || '#888'`.
- Count shown as `(N)` badge.
- `defaultOpen` controls initial state via `useState`.

**ATTENTION section:**

Merge two data sources:
```typescript
const attentionTasks = (agentTasks ?? []).filter(
  t => t.requires_action && (t.status === 'working' || t.status === 'review')
);
const attentionNotifs = (notifications ?? []).filter(
  n => n.notification_type === 'action_required' && !n.acknowledged
);
const attentionCount = attentionTasks.length + attentionNotifs.length;
```

Render attention tasks as `TaskCard` (reuse from ActivityDrawer), attention
notifications as `NotificationCard` (reuse from NotificationDropdown). Both
within the same section, interleaved by timestamp if desired (optional — keeping
them grouped by type is fine for v1).

Accent color: `#f0b060` (amber).
Only render section when `attentionCount > 0`.

**ACTIVE section:**

```typescript
const activeTasks = (agentTasks ?? []).filter(
  t => t.status === 'working' && !t.requires_action
);
```

Render as `TaskCard` components (from ActivityDrawer). Accent color: `#50b0a0`
(teal/green). Default open. Hidden when count is 0.

**NOTIFICATIONS section:**

```typescript
const infoNotifs = (notifications ?? []).filter(
  n => !(n.notification_type === 'action_required' && !n.acknowledged)
);
```

This includes info, error, and already-acknowledged action_required
notifications. Render as `NotificationCard` components. Show unread count in
header. Default open when unread count > 0, collapsed when all read. Hidden
when count is 0.

**KANBAN section:**

Compact inline kanban board. Use the current `MissionControl.tsx` column logic
but rendered inline within the panel at `380px` width instead of full-screen.

Column layout: 4 mini-columns as a horizontal grid
(`grid-template-columns: repeat(4, 1fr)`, `gap: 4px`).

Each column header: column name + count badge. Cards are minimal: just status
dot + title + AD number (no full detail like the standalone MissionControl).
Click a card to expand inline (or do nothing for v1 — keep it read-only
compact).

Default collapsed. Accent color: `#d0a030` (gold, matches current
MISSION CTRL styling).

**RECENT section:**

```typescript
const recentTasks = (agentTasks ?? []).filter(
  t => t.status === 'done' || t.status === 'failed'
).sort((a, b) => (b.completed_at ?? 0) - (a.completed_at ?? 0))
.slice(0, 10);
```

Render as `TaskCard` components (compact, no expand by default). Default
collapsed. Accent color: `#666`.

### 2. Shared card components — extract from existing files

**Move `TaskCard` and helpers** out of `ActivityDrawer.tsx` into a shared
location. Two options:
- **Option A (simpler):** Just import from ActivityDrawer by exporting the
  component. But ActivityDrawer.tsx will be deleted.
- **Option B (preferred):** Extract `TaskCard`, `SectionHeader`,
  `DEPT_COLORS`, `STATUS_COLORS`, and `formatElapsed` into a new shared file:
  `ui/src/components/bridge/BridgeCards.tsx`. Also move `NotificationCard`,
  `TYPE_COLORS`, `DEPT_COLORS`, and `formatRelativeTime` from
  `NotificationDropdown.tsx` into the same file (or a sibling
  `BridgeNotifications.tsx`).

Use Option B: create `ui/src/components/bridge/` directory with:
- `BridgeCards.tsx` — `TaskCard`, `DEPT_COLORS`, `STATUS_COLORS`,
  `formatElapsed` (extracted from ActivityDrawer)
- `BridgeNotifications.tsx` — `NotificationCard`, `TYPE_COLORS`,
  `formatRelativeTime` (extracted from NotificationDropdown)
- `BridgeKanban.tsx` — Compact kanban grid (extracted from MissionControl, but
  adapted for 380px inline width instead of full-screen)

These are internal sub-components of the Bridge — not general-purpose shared
components. The `bridge/` directory makes this clear.

### 3. Replace header buttons in IntentSurface.tsx

**Remove** the three separate buttons (NOTIF, ACTIVITY, MISSION CTRL) and
replace with a single BRIDGE button.

**Remove:**
- The NOTIF button block and `notifOpen` local state
- The ACTIVITY button block
- The MISSION CTRL button block
- The `<NotificationDropdown>` render
- The `<MissionControl>` conditional render
- The `<ActivityDrawer>` render
- Import of `NotificationDropdown`, `MissionControl`, `ActivityDrawer`

**Add:**
- Import `BridgePanel` from `./BridgePanel`
- Single BRIDGE button:
  ```tsx
  <div style={{
    position: 'fixed',
    top: 12,
    right: 12,
    zIndex: 25,
    pointerEvents: 'auto',
  }}>
    <button
      onClick={() => useStore.setState(s => ({ bridgeOpen: !s.bridgeOpen }))}
      style={{
        padding: '3px 8px',
        borderRadius: 4,
        border: `1px solid ${bridgeOpen ? 'rgba(240,176,96,0.4)' : 'rgba(255,255,255,0.15)'}`,
        background: bridgeOpen ? 'rgba(240,176,96,0.15)' : 'rgba(10,10,18,0.6)',
        color: attentionCount > 0 ? '#f0b060' : (bridgeOpen ? '#f0b060' : '#888'),
        fontSize: 9,
        fontWeight: 600,
        letterSpacing: 1,
        cursor: 'pointer',
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      BRIDGE{attentionCount > 0 ? ` (${attentionCount})` : ''}
    </button>
  </div>
  ```
- Render `<BridgePanel>`:
  ```tsx
  <BridgePanel
    open={bridgeOpen}
    onClose={() => useStore.setState({ bridgeOpen: false })}
  />
  ```

**Attention count for badge:** Compute in IntentSurface:
```typescript
const agentTasks = useStore(s => s.agentTasks);
const notifications = useStore(s => s.notifications);
const bridgeOpen = useStore(s => s.bridgeOpen);

const attentionCount =
  (agentTasks?.filter(t => t.requires_action).length ?? 0) +
  (notifications?.filter(n => n.notification_type === 'action_required' && !n.acknowledged).length ?? 0);
```

### 4. Update Zustand store

In `ui/src/store/useStore.ts`:

**Replace:**
- `missionControlView: boolean` → remove
- `activityDrawerOpen: boolean` → remove

**Add:**
- `bridgeOpen: boolean` — initial value `false`
- `mainViewer: 'canvas' | 'kanban'` — initial value `'canvas'`

**Update `handleEvent`:**
- No event handler changes needed — `agentTasks`, `notifications`, and
  `missionControlTasks` are all already populated by existing event handlers.

**Update any external references to old state:**
- `AgentTooltip.tsx` currently sets `activityDrawerOpen: true` for the "View in
  Activity" click-through. Change to `bridgeOpen: true`.

### 5. Update AgentTooltip click-through

In `ui/src/components/AgentTooltip.tsx`, the "View in Activity" button currently
does:
```typescript
useStore.setState({ activityDrawerOpen: true });
```

Change to:
```typescript
useStore.setState({ bridgeOpen: true });
```

Also update the label from "View in Activity" to "View in Bridge" (or just
"Open Bridge").

### 6. Delete old components

After the Bridge is working:

- **Delete** `ui/src/components/ActivityDrawer.tsx` — functionality moved to
  `BridgePanel.tsx` + `bridge/BridgeCards.tsx`
- **Delete** `ui/src/components/NotificationDropdown.tsx` — functionality moved
  to `BridgePanel.tsx` + `bridge/BridgeNotifications.tsx`
- **Delete** `ui/src/components/MissionControl.tsx` — functionality moved to
  `bridge/FullKanban.tsx` (main viewer) + `bridge/BridgeKanban.tsx` (compact)

Remove any lingering imports of these deleted files from IntentSurface or
elsewhere.

### 7. Main Viewer switching in CognitiveCanvas parent

In whatever component renders `<Canvas>` (likely `CognitiveCanvas.tsx` or
`IntentSurface.tsx`), wrap the canvas rendering with a viewer mode check:

```typescript
const mainViewer = useStore(s => s.mainViewer);
```

When `mainViewer === 'canvas'`, render the existing `<Canvas>` tree as-is.
When `mainViewer === 'kanban'`, render `<FullKanban />` instead.

The `<FullKanban />` component is the full-width kanban board — essentially the
current `MissionControl.tsx` layout adapted to coexist with the Bridge panel
(not full-screen opaque overlay, but a normal in-flow component that fills the
available center area).

### 8. ViewSwitcher component

Create a minimal `ViewSwitcher` component rendered in IntentSurface (or the
canvas parent) when `mainViewer !== 'canvas'`:

```typescript
function ViewSwitcher() {
  const mainViewer = useStore(s => s.mainViewer);
  if (mainViewer === 'canvas') return null;

  return (
    <div style={{
      position: 'fixed', top: 12, left: 12, zIndex: 25,
      display: 'flex', gap: 4, pointerEvents: 'auto',
    }}>
      <button
        onClick={() => useStore.setState({ mainViewer: 'canvas' })}
        style={{
          padding: '3px 8px', borderRadius: 4, fontSize: 9,
          fontWeight: 600, letterSpacing: 1, cursor: 'pointer',
          fontFamily: "'JetBrains Mono', monospace",
          background: mainViewer === 'canvas' ? 'rgba(240,176,96,0.15)' : 'rgba(10,10,18,0.6)',
          border: '1px solid rgba(255,255,255,0.15)',
          color: mainViewer === 'canvas' ? '#f0b060' : '#888',
        }}
      >CANVAS</button>
      <button
        onClick={() => useStore.setState({ mainViewer: 'kanban' })}
        style={{
          /* same styling pattern, active when mainViewer === 'kanban' */
        }}
      >KANBAN</button>
    </div>
  );
}
```

### 9. KANBAN expand button in Bridge panel

In the compact KANBAN section within `BridgePanel.tsx`, add a small expand
icon/button to the section header. When clicked:
```typescript
useStore.setState({ mainViewer: 'kanban' });
```

This promotes the kanban from compact sidebar view to full center view. The
section header styling should indicate this is expandable (e.g., a small ⬔ or
↗ icon on the right side of the header, next to the chevron).

## Files to create

- `ui/src/components/BridgePanel.tsx` — unified panel
- `ui/src/components/bridge/BridgeCards.tsx` — TaskCard, shared colors, helpers
- `ui/src/components/bridge/BridgeNotifications.tsx` — NotificationCard, helpers
- `ui/src/components/bridge/BridgeKanban.tsx` — compact inline kanban for sidebar
- `ui/src/components/bridge/FullKanban.tsx` — full-width kanban for main viewer
- `ui/src/components/ViewSwitcher.tsx` — top-left tab switcher (canvas/kanban)

## Files to modify

- `ui/src/components/IntentSurface.tsx` — replace 3 buttons with 1 BRIDGE
  button, replace 3 panel renders with 1 BridgePanel render, add ViewSwitcher
- `ui/src/store/useStore.ts` — replace `missionControlView` +
  `activityDrawerOpen` with `bridgeOpen` + `mainViewer`
- `ui/src/components/AgentTooltip.tsx` — update click-through to use
  `bridgeOpen`
- `ui/src/components/CognitiveCanvas.tsx` (or parent) — conditional render
  based on `mainViewer`

## Files to delete

- `ui/src/components/ActivityDrawer.tsx`
- `ui/src/components/NotificationDropdown.tsx`
- `ui/src/components/MissionControl.tsx`

## Files to read first

- `ui/src/components/IntentSurface.tsx` — current 3-button layout, panel renders
- `ui/src/components/ActivityDrawer.tsx` — TaskCard, SectionHeader, DEPT_COLORS,
  STATUS_COLORS, formatting helpers (all need extraction)
- `ui/src/components/NotificationDropdown.tsx` — NotificationCard, TYPE_COLORS,
  formatRelativeTime (all need extraction)
- `ui/src/components/MissionControl.tsx` — kanban columns, card rendering
  (becomes FullKanban and compact BridgeKanban)
- `ui/src/components/CognitiveCanvas.tsx` — where the 3D canvas renders,
  understand how to conditionally swap with kanban
- `ui/src/components/AgentTooltip.tsx` — click-through reference
- `ui/src/store/useStore.ts` — state fields to update
- `ui/src/store/types.ts` — AgentTaskView, NotificationView, MissionControlTask

## Tests

Update existing and add new vitest tests in `ui/src/__tests__/`:

1. **test bridgeOpen store field** — set and read `bridgeOpen` from store,
   verify default is `false`
2. **test mainViewer store field** — verify default is `'canvas'`, can switch
   to `'kanban'` and back
3. **test missionControlView removed** — verify `missionControlView` is no
   longer in the store
4. **test activityDrawerOpen removed** — verify `activityDrawerOpen` is no
   longer in the store
5. **test attention count computation** — with mixed `requires_action` tasks
   and `action_required` notifications, verify the combined count
6. **Preserve all existing event handler tests** — `notification`,
   `notification_ack`, `notification_snapshot`, `task_created`, etc. must still
   pass since the data layer is unchanged

Remove or update tests that reference `activityDrawerOpen` or
`missionControlView` — replace with `bridgeOpen`.

## Acceptance criteria

- Single BRIDGE button replaces NOTIF, ACTIVITY, MISSION CTRL
- BRIDGE button shows combined attention count (requires_action tasks +
  action_required notifications)
- Bridge panel slides in from right with glass morphism styling
- ATTENTION section shows merged attention items at top (always expanded)
- ACTIVE, NOTIFICATIONS, KANBAN, RECENT sections follow in priority order
- Empty sections are hidden (no empty headers)
- Sections are collapsible with chevron indicators
- TaskCard and NotificationCard retain all existing functionality (expand,
  approve/reject, ack, click-to-acknowledge)
- "Mark all read" in header acknowledges all notifications
- AgentTooltip "View in Activity" opens Bridge instead
- Old panel components (ActivityDrawer, NotificationDropdown, MissionControl)
  are deleted
- `missionControlView` and `activityDrawerOpen` removed from store, replaced
  with `bridgeOpen` and `mainViewer`
- **Main viewer switches between canvas and kanban** via `mainViewer` state
- **Kanban expand** from Bridge panel promotes to full center view
- **ViewSwitcher** appears top-left when non-canvas view is active
- **Canvas remains default** — ViewSwitcher hidden when on canvas
- All existing vitest tests pass (updated for new state field names)
- New tests cover `bridgeOpen`, `mainViewer`, and attention count computation
- 3D canvas remains visible and interactive when Bridge is open (canvas mode)
- TypeScript compiles with no errors (`npx tsc --noEmit`)
