# AD-837 — Ward Room Detachable Window Mode (docked ↔ floating, resizable, full-screen)

**Status:** Ready
**Dependencies:** AD-485 (Ward Room panel), AD-721 (AgentProfilePanel floating-window pattern — the convention to follow), HXI Design Principles #3 (stroke-SVG glyphs), #5 (progressive disclosure)
**Estimated tests:** 8 vitest (frontend only)
**Repo:** OSS (`d:\ProbOS`) — this is how the product *works* (UI surface), not how it makes money.

> **Operator intent (2026-05-31):** an in-app floating window inside the existing HXI,
> matching the feel of the **Agent Profile card / 1:1 chat panel**
> ([`AgentProfilePanel.tsx`](../ui/src/components/profile/AgentProfilePanel.tsx)) —
> draggable, corner-resizable, scalable to full screen, one-click switch between docked
> sidebar and floating window. NOT a separate OS window (that remains the AD-837b seam).
> **The Builder MUST reuse the AgentProfilePanel drag/resize/persist convention, not
> reinvent it (DRY).**

## Problem

The Ward Room is hard-pinned as a 420px-wide left **docked sidebar**:

```tsx
// ui/src/components/wardroom/WardRoomPanel.tsx:130-146
return (
  <div style={{
    position: 'fixed',
    top: 0, left: 0, bottom: 0,
    width: 420,
    ...
    transform: open ? 'translateX(0)' : 'translateX(-100%)',
```

There is no way to detach it into a movable, resizable window or to expand it to full
screen. The crew-communication surface (channels, threads, DM log — the screenshot's
Engineering duty report) is the densest reading/triage surface in the HXI, and 420px is
cramped for multi-column thread reading. HXI Principle #5 (progressive disclosure driven
by engagement) and #9 (alert-driven layout) both argue the operator should be able to
promote the Ward Room from an ambient docked strip to a focused, full-screen workspace
when triaging, then dock it again.

## Solution

Introduce a **display-mode** for the Ward Room panel with three states and a one-click
toggle in the panel header:

| Mode | Behavior |
|------|----------|
| `docked` | Current 420px left sidebar (unchanged default — regression-safe) |
| `floating` | Detached window: draggable by header, resizable from right/bottom edges + bottom-right corner, with a min size (e.g. 360×320) and a max of the viewport |
| `maximized` | Floating window scaled to (near) full viewport; restores to the prior floating rect |

The toggle path is **docked → floating → (maximize/restore) → docked**, switchable any
time. Mode, last floating rect (`{x, y, w, h}`), and maximized flag persist to
`localStorage` and rehydrate on mount — mirroring the existing
[`loadSidebarCollapsed`](../ui/src/components/sidebar/ThreadSidebar.tsx) persistence
precedent. Pure frontend; **no backend, no API, no store-schema change to server data.**

This stays in-app (a floating panel that scales to full screen), NOT a true OS-level
`window.open` popup — a real detached browser/Tauri window requires React-portal-into-popup
plumbing and is documented as the AD-837b seam.

### Section 1 — Store: display-mode state + persistence

File: `ui/src/store/useStore.ts`

Add to the Ward Room slice (near
[`wardRoomOpen`/`openWardRoom`/`closeWardRoom`, L353/499/500](../ui/src/store/useStore.ts)):

```ts
wardRoomDisplayMode: 'docked' | 'floating' | 'maximized';
wardRoomWindowRect: { x: number; y: number; w: number; h: number };
setWardRoomDisplayMode: (mode: 'docked' | 'floating' | 'maximized') => void;
setWardRoomWindowRect: (rect: { x: number; y: number; w: number; h: number }) => void;
```

- Defaults: `wardRoomDisplayMode: 'docked'` (regression-safe), a sensible centered initial
  rect (e.g. `{ x: 80, y: 80, w: 720, h: 640 }`).
- `setWardRoomDisplayMode` / `setWardRoomWindowRect` write through to `localStorage`
  (keys `probos.wardroom.mode`, `probos.wardroom.rect`) using the same try/catch
  log-and-degrade pattern as the sidebar-collapsed helper.
- Add a module-level `loadWardRoomLayout()` exported helper (parse + validate persisted
  values, fall back to defaults on any error) used to seed the store — do NOT read
  `localStorage` inside the reducer body.

### Section 2 — Panel: render per display mode

File: `ui/src/components/wardroom/WardRoomPanel.tsx`

Replace the hard-coded container style ([L130-146](../ui/src/components/wardroom/WardRoomPanel.tsx))
with a mode-derived style:

- `docked`: existing fixed-left-420 style (byte-identical to today).
- `floating`: `position: fixed` at `wardRoomWindowRect` `{x,y,w,h}`, a visible border +
  shadow, `zIndex` above the docked value (current `20`).
- `maximized`: `position: fixed; inset: <small margin>` filling the viewport.

Keep the existing slide-in `transform`/`pointerEvents`/`open` gating for `docked` only;
floating/maximized use opacity/visibility gating instead (a window doesn't slide from the
edge). The body (`WardRoomChannelList`/`WardRoomThreadList`/`WardRoomThreadDetail`/`DmActivityLog`)
renders unchanged in all modes — only the chrome changes.

### Section 3 — Header controls (dock/undock + maximize/restore)

File: `ui/src/components/wardroom/WardRoomPanel.tsx` header block ([L147-170](../ui/src/components/wardroom/WardRoomPanel.tsx))

Add two glyph buttons next to the existing `Close` control:

- **Dock/Undock** — `docked → floating` and `floating/maximized → docked`.
- **Maximize/Restore** — `floating → maximized` and `maximized → floating` (hidden in
  `docked` mode).

Per HXI Principle #3, add the needed icons as **stroke-based inline SVG glyphs**
(`strokeWidth: 1.5`, `strokeLinecap: round`, amber active / dim inactive) to
`ui/src/components/icons/Glyphs.tsx` — NO emoji. Suggested glyph names: `Dock`, `Undock`,
`Maximize`, `Restore`. Reuse the existing `Close`/`ArrowLeft` import pattern.

### Section 4 — Drag + resize for floating mode (FOLLOW AgentProfilePanel)

File: `ui/src/components/wardroom/WardRoomPanel.tsx` (or a small co-located
`useWardRoomWindowDrag.ts` hook — keep `WardRoomPanel` under the SRP line size)

**Mirror the existing, proven convention in
[`AgentProfilePanel.tsx`](../ui/src/components/profile/AgentProfilePanel.tsx) — do NOT
invent a parallel implementation.** That panel is the canonical HXI floating window
(the Agent Profile card / 1:1 chat surface the operator referenced):

- **Drag** ([`AgentProfilePanel.tsx:110-130`](../ui/src/components/profile/AgentProfilePanel.tsx)):
  `onMouseDown` on the header captures `dragOffset = clientX/Y - pos`; a `mousemove`
  listener (added on drag-start, removed on `mouseup`) clamps
  `newX = clamp(0, innerWidth - w)`, `newY = clamp(0, innerHeight - 100)` and writes the
  position. Exclude the control glyphs from the drag handle (`stopPropagation`).
- **Resize** ([`AgentProfilePanel.tsx:132-152`](../ui/src/components/profile/AgentProfilePanel.tsx)):
  bottom-right corner handle; `onResizeMouseDown` records `resizeStart`; `mousemove`
  computes `nw = clamp(320, innerWidth - 40, startW + dw)`,
  `nh = clamp(360, innerHeight - 40, startH + dh)`. Reuse the same min/clamp constants.
- **Persistence**: AgentProfilePanel persists size to `localStorage` key
  `hxi_profile_panel_size`. Follow the same pattern with the AD-837 keys
  (`probos.wardroom.rect` / `.mode`).
- Disabled in `docked` and `maximized` modes.
- Listeners are added on mouse-down and removed on `mouseup` / unmount — no global
  always-on listeners (matches AgentProfilePanel's `useEffect` add/remove discipline).

## Tests

New file: `ui/src/components/wardroom/__tests__/WardRoomPanel.windowmode.test.tsx`

1. **Default docked** — fresh store renders the 420px left-fixed container.
2. **Undock → floating** — clicking Undock sets `displayMode='floating'` and renders the
   window at the persisted/default rect.
3. **Maximize → restore** — maximize fills the viewport; restore returns to the prior
   floating rect.
4. **Dock from floating** — Dock returns to the 420px sidebar; maximize control hidden in
   docked mode.
5. **Persistence write** — changing mode writes `probos.wardroom.mode` to `localStorage`.
6. **Persistence load** — `loadWardRoomLayout()` rehydrates a persisted floating rect;
   falls back to defaults on malformed JSON (edge).
7. **Resize clamps** — programmatic resize below min / above viewport clamps to bounds.
8. **No-emoji guard** — assert the new header controls render SVG (`querySelector('svg')`),
   not emoji text (HXI Principle #3).

Run: `cd ui && npx vitest run src/components/wardroom/__tests__/WardRoomPanel.windowmode.test.tsx`

## What This Does NOT Change

- No backend, no API endpoint, no `routers/`, no server-side Ward Room data model.
- No true OS-level detached browser/Tauri window (`window.open` portal) — that is the
  documented **AD-837b** seam.
- No change to Ward Room content components (channel/thread/DM rendering untouched).
- No change to the `docked` default — zero-config first paint is identical to today.
- No change to other HXI panels (Crew, Notebooks, Records, etc.). If a shared
  detachable-window primitive is later wanted, generalize in a follow-on AD — do NOT
  refactor the other panels here.

## Tracking

- `PROGRESS.md` — add AD-837 CLOSED entry; bump the vitest tracker count.
- `decisions-era-5-unification.md` — append AD-837: Ward Room docked↔floating↔maximized
  display mode with drag/resize + localStorage persistence; AD-837b seam for true OS-window
  detach.

## Acceptance Criteria

1. Operator can toggle the Ward Room from docked sidebar to a floating, draggable,
   resizable window and to full-screen, and back, from the panel header.
2. Mode + window geometry persist across reloads.
3. `docked` default is byte-identical to pre-AD-837 behavior.
4. New header controls are stroke-SVG glyphs (no emoji) per HXI Principle #3.
5. 8 vitest pass; `cd ui && npm run build` green (BF-279 gate).
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-31)

```
ui/src/App.tsx:220                                   <WardRoomPanel /> render site
ui/src/components/wardroom/WardRoomPanel.tsx:105      export function WardRoomPanel()
ui/src/components/wardroom/WardRoomPanel.tsx:130-146  hard-coded position:fixed left/width:420 container
ui/src/components/wardroom/WardRoomPanel.tsx:147-170  header block + onClose <Close size={16} />
ui/src/components/wardroom/WardRoomPanel.tsx:6        import { ArrowRight, ArrowLeft, Close } from '../icons/Glyphs'
ui/src/store/useStore.ts:353                          wardRoomOpen: boolean
ui/src/store/useStore.ts:499-500                      openWardRoom / closeWardRoom actions
ui/src/components/sidebar/ThreadSidebar.tsx           loadSidebarCollapsed — localStorage-persist precedent
ui/src/components/profile/AgentProfilePanel.tsx:40    isDragging state — canonical floating-window pattern to follow
ui/src/components/profile/AgentProfilePanel.tsx:110   onMouseDown drag handler + viewport clamp
ui/src/components/profile/AgentProfilePanel.tsx:132   onResizeMouseDown bottom-right corner resize, clamp 320x360..viewport-40
ui/src/components/profile/AgentProfilePanel.tsx:53    hxi_profile_panel_size localStorage size-persist precedent
```
